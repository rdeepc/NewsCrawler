import scrapy
import logging
import datetime

from NewsCrawler.items import DhakaTribuneItem
from newspaper import Article

from NewsCrawler.Helpers.CustomNERTagger import Tagger
from NewsCrawler.Helpers.date_helper import increase_day_by_one, DATETIME_FORMAT, dateobject_to_split_date
from NewsCrawler.credentials_and_configs.stanford_ner_path import STANFORD_CLASSIFIER_PATH, STANFORD_NER_PATH

from scrapy.exceptions import CloseSpider

from elasticsearch import Elasticsearch
from pymongo import MongoClient

es = Elasticsearch()



class DhakaTribuneSpider(scrapy.Spider):
	name = 'dhakatribune'

	def __init__(self, start_page=0, end_page=2):
		self.start_page = int(start_page)
		self.end_page = int(end_page)
		self.tagger = Tagger(classifier_path=STANFORD_CLASSIFIER_PATH, ner_path=STANFORD_NER_PATH)
		client = MongoClient()
		self.db = client.news_db

	def start_requests(self):
		self.begin_page = str(self.start_page)

		#Begin scraping from here
		self.base_url = 'http://archive.dhakatribune.com/archive?page=' + str(self.start_page)

		self.id = 0

		yield scrapy.Request(self.base_url, self.parse)

	# print out the collected attributes
	def debug(self, news_item):
		debug_item = {key: news_item[key] for key in news_item.keys() }
		self.logger.info(debug_item)

	
	def parse(self, response):
		self.main_selection = response.xpath("//div[@class='post-inner']")

		for selection in self.main_selection:
			news_item = DhakaTribuneItem()
			news_item['newspaper_name'] = 'Dhaka Tribune'
			news_item['url'] = selection.xpath("header/h2/a/@href").extract_first()
			news_item['title'] = selection.xpath("header/h2/a/text()").extract_first()
			news_item['published_date'] = selection.xpath("header/div[1]/text()").extract_first()
			news_item['excerpt'] = selection.xpath("div[1]/p/text()").extract_first().strip()
			news_item['reporter'] = selection.xpath("header/div[1]/span/a/text()").extract_first()
			
			request = scrapy.Request(news_item['url'], callback=self.parseNews)
			request.meta['news_item'] = news_item

			yield request

		# increase page count by one
		self.start_page += 1

		# Next page url 
		self.next_page = self.base_url + str(self.start_page)

		if self.start_page > self.end_page:
			raise CloseSpider('Done scraping from page: ' + str(self.begin_page) + ' to ' + str(self.end_page))
		
		try:
			self.logger.info("TRYING")
			yield scrapy.Request(self.next_page, callback=self.parse)
		except:
			self.logger.info("PROBLEM")
			self.start_page += 1
			self.next_page = self.base_url + str(self.start_page)
			yield scrapy.Request(self.next_page, callback=self.parse)

	def parseNews(self, response):
		# Getting the news item
		news_item = response.meta['news_item']

		# Get shoulder if available
		news_item['shoulder'] = response.xpath("//div[@class='shoulder']/text()").extract_first()

		# Get image urls with captions
		news_item['images'] = response.xpath("//ul[@class='singleslider']/li/img/@src").extract_first()
		
		# If there is an image, try to get the other attributes
		if news_item['images'] != None:
			news_item['image_captions'] = ''.join([text.strip() for text in response.xpath("//ul[@class='singleslider']/li/text()").extract()])
			credit_text = response.xpath("//ul[@class='singleslider']/li/span/text()").extract_first()
			if credit_text != None:
				news_item['images_credit'] = credit_text.replace('Photo- ', '')

		# Getting the Article
		news_item['article'] = ''.join([text.strip() for text in response.xpath("//div[contains(@class,'article-content')]//p/text()").extract()])

		reporter_info_available = True if len(response.xpath("//div[@class='author-info']")) > 0 else False

		if reporter_info_available == False:
			# Trying to get info from the post
			news_item['about_reporter'] = response.xpath("//div[contains(@class,'article-content')]//em/text()").extract_first()
		
		else:
			# Trying to get info outside the post 
			news_item['about_reporter'] = response.xpath("//div[@class='author-info']//p[@class='description']/text()").extract_first()

		# Get the news category
		news_item['category'] = response.xpath("//span[@class='art-tagss']/a/text()").extract_first()

		# Checking if breadcrumb exists
		breadcrumb = response.xpath("//div[@class='node ']/span/span/text()").extract_first()

		# Get the breadcrumb
		if breadcrumb != None:
			news_item['breadcrumb'] = [item.strip() for item in breadcrumb.split('>>') if item != ' ']

		# Get current time 
		news_item['crawl_time'] = datetime.datetime.now().strftime(DATETIME_FORMAT)

		news_item['ml_tags'] = None
		news_item['sentiment'] = None

		self.tag_it(news_item)

		# Creating the doc
		doc = {
			"id": news_item[]
            "news_url" : news_item['url'],
            "reporter" : news_item['reporter'],
			"about_reporter" : news_item['about_reporter'],
            "published" : news_item['published_date'],
            "title" : news_item['title'],
            "content" : news_item['article'],
            "images" : news_item['images'],
            "image_captions" : news_item['image_captions'],
            "breadcrumb" : news_item['breadcrumb'],
            "sentiment" : news_item['sentiment'],
            "ml_tags" : None,
            "shoulder" : news_item['shoulder'],
            
            "ner_person" : news_item['ner_person'],
            "ner_organization" : news_item['ner_organization'],
            "ner_money" : news_item['ner_money'],
            "ner_time" : news_item['ner_time'],
            "ner_location" : news_item['ner_location'],
            "ner_percent" : news_item['ner_percent'],

            "ner_list_person" : news_item['ner_list_person'],
            "ner_list_organization" : news_item['ner_list_organization'],
            "ner_list_money" : news_item['ner_list_money'],
            "ner_list_time" : news_item['ner_list_time'],
            "ner_list_location" : news_item['ner_list_location'],
            "ner_list_percent" : news_item['ner_list_percent'],

            "generated_keywords" : news_item['generated_keywords'],
            "generated_summary" : news_item['generated_summary'],
            "crawled_time" : news_item['crawl_time'],
            "timestamp" : news_item['crawl_time'],
        }

		self.db.news_db.insert_one(doc)

		self.debug(news_item)

	def tag_it(self, news_item):
		# #Applying NLP from newspaper package
		article = Article(url=news_item['url'])
		article.download()
		article.parse()
		article.nlp()

		news_item['generated_summary'] = article.summary
		news_item['generated_keywords'] = article.keywords

		# Tagging the article
		try:
			self.tagger.entity_group(news_item['article'])
		except:
			self.logger.info("NER CRASHED")

		news_item['ner_person'] = self.tagger.PERSON
		news_item['ner_organization'] = self.tagger.ORGANIZATION
		news_item['ner_time'] = self.tagger.TIME
		news_item['ner_percent'] = self.tagger.PERCENT
		news_item['ner_money'] = self.tagger.MONEY
		news_item['ner_location'] = self.tagger.LOCATION

		# Contains all occurances
		news_item['ner_list_person'] = self.tagger.LIST_PERSON
		news_item['ner_list_organization'] = self.tagger.LIST_ORGANIZATION
		news_item['ner_list_time'] = self.tagger.LIST_TIME
		news_item['ner_list_percent'] = self.tagger.LIST_PERCENT
		news_item['ner_list_money'] = self.tagger.LIST_MONEY
		news_item['ner_list_location'] = self.tagger.LIST_LOCATION