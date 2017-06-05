# -*- coding: utf-8 -*-
import youtube_dl
import scrapy
import ConfigParser
import json
import string
import os
import subprocess
import time
from service.logger import Logger
from service.database import get_database
import service.utils
import re
from scrapy.exceptions import CloseSpider
import service.mail
import sys
reload(sys)
sys.setdefaultencoding('utf-8')

logger = Logger.get_logger('chinanews')


class ChinanewsSpider(scrapy.Spider):
    name = "chinanews"
    allowed_domains = ["chinanews.com"]
    callbacked = None
    video_id = None

    def __init__(self, url, uuid, upload_url, callback, check_video_url=None, *args, **kwargs):
        super(ChinanewsSpider, self).__init__(*args, **kwargs)

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

    def parse(self, response):
        print response.url

        try:
            self.video_id = self.match_id(response.url)
        except AssertionError, e:
            raise CloseSpider('link not supported')

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
            # 'noplaylist': True
        }

        print ydl_opts

        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download(self.start_urls)

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
                "cover": result[4],
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
                logger.error('upload video error', self.uuid)
                raise CloseSpider('upload oss failed')
            # os.remove('cache/' + info['id'] + '*')

            if 'thumbnail' in info:
                cover = service.utils.get_clip_cover_url(info['thumbnail'], self.uuid)
            else:
                cover = ''
            data = {
                "video_id": self.uuid,
                "state": 1,
                "message": u'成功',
                "length": info['duration'],
                "play_id": self.uuid,
                "size": total_bytes,
                "cover": cover,
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
                'easub_uuid': self.uuid,
                'cover': cover
            }
            self.db.save_video(video_data)

        if d['status'] == 'error':
            raise CloseSpider('download failed')

    def match_id(self, url):
        regx = r'https?://(?:www\.)?chinanews\.com/(?:[^/]+/)*(?P<id>\d+)'
        m = re.compile(regx).match(url)
        assert m
        return m.group('id')

    def closed(self, reason):
        print '[closed]', reason
        if not self.callbacked:
            data = {
                "video_id": self.uuid,
                "state": 0,
                "message": reason,
                "length": 0,
                "play_id": '',
                "cover": '',
                "title": ''
            }
            service.utils.callback_result(self.callback, data=data)
            service.mail.send_mail('spider failed:' + self.name, self.uuid + ' ' + reason)
        logger.info('[closed reason]' + reason + "[uuid]" + self.uuid)
        if self.video_id:
            # subprocess.Popen('rm -rf ' + 'cache/' + self.uuid + '*', shell=True)
            service.utils.remove_all_files('cache/', self.uuid)
