#!/usr/bin/env python3

'''
Created on Oct 30, 2018

@author: Dmytro Dubrovny <dubrovnyd@gmail.com>
'''
from sitefs import RootDirectory, Directory, File, CacheControl, sanitize_filename, mount
from bs4 import BeautifulSoup
import requests
import regex
import json
import sys


class Reader(object):

    def __init__(self):
        self.web_url = 'http://animevost.org'
        self.api_url = 'https://api.animevost.org/v1'

    def list_latest(self):
        page = requests.get(self.web_url)
        soup = BeautifulSoup(page.text, 'html.parser')
        last_page = max([int(a.text) for a in soup.find(
            attrs={"class": "block_4"}).findAll('a')])
        return ["%03d" % page for page in range(1, ++last_page)]

    def list_titles(self, page):
        page = requests.get("%s/page/%d" % (self.web_url, page))
        soup = BeautifulSoup(page.text, 'html.parser')
        index = 0
        for div in soup(attrs={"class": "shortstoryHead"}):
            title = {'name': "%01d %s" % (index, sanitize_filename(div.a.text)), 'id': int(
                regex.search('([0-9]+)[^/]+html', div.a.get('href'))[1])}
            index += 1
            yield title

    def list_series(self, title_id):
        page = requests.post("%s/playlist" % self.api_url,
                             {'id': title_id}, None)
        print
        series = json.loads(page.text)
        for item in series:
            (number, name) = item['name'].split(' ')
            if 'std' in item:
                yield {'name': "%03d %s std" % (int(number), name), 'url': item['std']}
            if 'hd' in item:
                yield {'name': "%03d %s hd" % (int(number), name), 'url': item['hd']}


class Item():
    def __init__(self):
        self.reader = Reader()


class Root(RootDirectory):
    def __init__(self):
        RootDirectory.__init__(self)
        self.children = [Latest()]


class Latest(Directory, CacheControl, Item):
    def __init__(self, ttl=20):
        Directory.__init__(self, 'Latest')
        CacheControl.__init__(self, ttl)
        Item.__init__(self)

    def get_children(self):
        if not self.is_cached():
            self.children = [Page(p) for p in self.reader.list_latest()]
            self.validate_cache()
        return self.children


class Page(Directory, CacheControl, Item):
    def __init__(self, page, ttl=60):
        Directory.__init__(self, page)
        CacheControl.__init__(self, ttl)
        Item.__init__(self)
        self.page = int(page)

    def get_children(self):
        if not self.is_cached():
            self.children = [Title(t)
                             for t in self.reader.list_titles(self.page)]
            self.validate_cache()
        return self.children


class Title(Directory, CacheControl, Item):
    def __init__(self, title, ttl=60):
        Directory.__init__(self, title['name'])
        CacheControl.__init__(self, ttl)
        Item.__init__(self)
        self.title = title

    def get_children(self):
        if not self.is_cached():
            self.children = [
                Record(r, self.get_name()) for r in self.reader.list_series(self.title['id'])]
            self.validate_cache()
        return self.children


class Record(File, Item):
    def __init__(self, record, title):
        File.__init__(self, "%s.m3u8" % record['name'])
        Item.__init__(self)
        self.record = record
        self.title = title

    def get_content(self):
        return str.encode("#EXTM3U\n#EXTINF:-1, %(title)s - %(name)s\n%(url)s\n"
                          % {'url': self.record['url'], 'title': self.title,
                              'name': self.record['name']})


if __name__ == '__main__':
    mount(sys.argv[1], Root(), 'animevostorg')
