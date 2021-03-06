# -*- coding: utf-8 -*-
import youtube_dl
import scrapy
import ConfigParser
import json
import string
import os
import time
from service.logger import Logger
from service.database import get_database
import service.utils
import re
from scrapy.exceptions import CloseSpider
import sys
from scrapy.selector import Selector
from scrapy.http import Request,FormRequest
import sys
reload(sys)
sys.setdefaultencoding('utf-8')

logger = Logger.get_logger('echo')

class EchoSpider(scrapy.Spider):
    name = 'echo'
    allowed_domains = ["app-echo.com"]
    callbacked = None
    video_id = None
    clip_id =None

    def __init__(self, url, uuid, upload_url, callback, check_video_url=None, *args, **kwargs):
        super(EchoSpider, self).__init__(*args, **kwargs)

        self.config = ConfigParser.ConfigParser()
        self.config.read("config/config.ini")
        self.uuid = uuid
        self.upload_url = upload_url
        self.callback = callback
        self.check_video_url = check_video_url
        # initialize db
        with open("config/database.cnf") as f:
            config = json.load(f)
        db_cls = get_database(config.get("database_type", None))
        self.db = db_cls(**config.get("database", {}))

        self.start_urls.append(url)
        print url
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.1.1; Nexus 6 Build/LYZ28E) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.95 Mobile Safari/537.36',
            'Host': 'www.app-echo.com',
            'Cookie': 'PHPSESSID=4d8dosv6miubuh1igoc6ofdfu6; echo_language=0fa769e85f49c8f39f1a51b419d5ec98c7821fcdb7666236b7c498a20cee27fea%3A2%3A%7Bi%3A0%3Bs%3A13%3A%22echo_language%22%3Bi%3A1%3Bs%3A2%3A%22cn%22%3B%7D; _csrf=0f742eba9cca1b0785a3283f9e28b89cb4ae5a6ceeaf35d328ba62505bb8751ca%3A2%3A%7Bi%3A0%3Bs%3A5%3A%22_csrf%22%3Bi%3A1%3Bs%3A32%3A%22Nd4K1ScPvyylRf2f2iO2n3opdyrDvogR%22%3B%7D; view_statistics_type=event.music-festival; Hm_lvt_8c9a0b394fc1f4d9177f4869cfd72618=1484472213; Hm_lpvt_8c9a0b394fc1f4d9177f4869cfd72618=1484472213; Hm_lvt_46b3b8e7eb78200527b089c276c81a7e=1484472113; Hm_lpvt_46b3b8e7eb78200527b089c276c81a7e=1484479163; MP_LIST=',
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'Accept-Language': 'en,zh-CN;q=0.8,zh;q=0.6',
            'Accept-Encoding': 'gzip, deflate, sdch',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        }
        #gettext = requests.get('http://www.app-echo.com/mv/1150', headers=self.headers)
        #gettext.encoding = 'utf-8'
        #gettext = gettext.text


    def start_requests(self):
        return [Request(self.start_urls[0],callback=self.parse,headers=self.headers)]

    def parse(self, response):
        try:
            self.video_id=self.match_id(url=response.url)
            print self.video_id
        except AssertionError, e:
            raise CloseSpider('link not supported')
        sel = Selector(response)
        video_link_list=sel.xpath('//video/@src').extract()
        video_link=video_link_list[0]
        print video_link

        logger.warn('[parse]' + response.url + ' [uuid]' + self.uuid + ' [video_id]' + self.video_id)
        if self.check_db():
            return

        ydl_opts = {
            'writeinfojson': True,
            'skip_download': False,
            'format': 'http-720p/high/hd/22/best',
            'outtmpl': 'cache/' + self.uuid + '_%(id)s.%(ext)s',
            # 'ignoreerrors': True,
            'progress_hooks': [self.hooks],
            # 'max_downloads': 1
        }

        print ydl_opts

        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download(video_link)

    def check_db(self):
        result = service.utils.search_video(video_id=self.video_id, page_url=self.start_urls[0],
                                            check_url=self.check_video_url)
        if result:
            print 'db note url:', self.start_urls[0]
            logger.warn('[db note url]' + self.start_urls[0] + '[uuid]' + self.uuid)
            data = {
                "video_id": self.uuid,
                "state": 1,
                "message": u'成功',
                "length": result[2],
                "play_id": result[0],
                "size": result[3],
                "cover": '',
                "title": result[1]
            }
            self.callbacked = service.utils.callback_result(self.callback, data=data)
            return True

    def hooks(self, d):

        if d['status'] == 'finished':
            filename = d['filename']
            l = filename.split('.')
            ext = l[len(l) - 1]
            print ext
            jsonfile = string.replace(filename, ext, 'info.json')
            info = json.loads(open(jsonfile).read())
            os.remove(jsonfile)
            if 'duration' not in info:
                info['duration'] = service.utils.getVideoLength(filename)

            total_bytes = os.path.getsize(filename)
            endpoint, backet, obj = service.utils.paseUploadUrl(self.upload_url)
            print endpoint, backet, obj
            uploadResult = service.utils.uploadVideo(filename, endpoint, backet, obj)

            if not uploadResult:
                raise CloseSpider('upload oss failed')
            # os.remove('cache/' + info['id'] + '*')

            data = {
                "video_id": self.uuid,
                "state": 1,
                "message": u'成功',
                "length": info['duration'],
                "play_id": self.uuid,
                "size": total_bytes,
                "cover": '',
                "title": info['title']
            }
            self.callbacked = service.utils.callback_result(self.callback, data=data)
            logger.info('[finished]' + str(self.callbacked) + '[uuid]' + self.uuid)

            if 'uploader' not in info:
                info['uploader'] = info['extractor']

            video_data = {
                'title': info['title'],
                'video_id': self.video_id,
                'author': info['uploader'],
                'publish': time.strftime('%Y-%m-%d %H:%M:%S'),
                'page_url': info['webpage_url'],
                'video_length': info['duration'],
                'video_size': total_bytes,
                'video_url': '',
                'easub_uuid': self.uuid
            }
            self.db.save_video(video_data)

        if d['status'] == 'error':
            print 'error', d['filename']
            raise CloseSpider('download failed')

    def match_id(self,url):
        regex='http://www.app-echo.com.{1,3}mv/(?P<id>\d*)'
        m = re.compile(regex).match(url)
        assert m
        return m.group('id')