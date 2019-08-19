#!/usr/bin/env python3

'''
Created on Oct 30, 2018

@author: Dmytro Dubrovny <dubrovnyd@gmail.com>
'''
from sitefs import Directory, File, sanitize_filename
import requests
import json
import time


class Reader(object):

    def __init__(self):
        self.api_url = 'https://api.animevost.org/v1'
        self.quantity = 99

    def get_pages(self):
        page = requests.get("%s/last?page=1&quantity=%d" % (self.api_url, self.quantity))
        series = json.loads(page.text)
        if len(series['data']) < self.quantity:
            self.quantity = len(series['data'])
        max_page = series['state']['count'] // self.quantity + 1
        return ["%03d" % page for page in range(1, max_page)]

    def get_titles(self, page):
        page = requests.get("%s/last?page=%d&quantity=%d" % (self.api_url, page, self.quantity))
        series = json.loads(page.text)
        index = 0
        for s in series['data']:
            index += 1
            title = {'title': "%02d %s" % (index, sanitize_filename(s['title'])), 'id': s['id']}
            yield title

    def get_series(self, title_id):
        page = requests.post("%s/playlist" % self.api_url,
                             {'id': title_id}, None)
        series = json.loads(page.text)
        std = []
        hd = []
        for item in series:
            if 'std' in item:
                std.append(Record(item['name'], item['std']))
            if 'hd' in item:
                hd.append(Record(item['name'], item['hd']))
        return {'std': sorted(std), 'hd': sorted(hd)}


class Item():

    def __init__(self):
        self.reader = Reader()


class Root(Directory):

    def __init__(self, quality):
        Directory.__init__(self, '', [Latest(quality, CacheControl(6000)), All(quality, CacheControl(6000))])
        self.quality = quality


class CacheControl():
    def __init__(self, ttl):
        self.cache = {'ttl': ttl, 'time': 0}

    def is_valid(self):
        return time.time() - self.cache['time'] < self.cache['ttl']

    def validate(self, ttl=None):
        if ttl != None:
            self.cache['ttl'] = ttl
        self.cache['time'] = time.time()

    def invalidate(self):
        self.cache['time'] = 0


class Latest(Directory, Item):

    def __init__(self, quality: str, cache: CacheControl):
        Directory.__init__(self, 'latest', [])
        self.cache = cache
        Item.__init__(self)
        self.quality = quality

    @property
    def children(self):
        if not self.cache.is_valid():
            self._children = [Title(t, self.quality, CacheControl(6000)) for t in self.reader.get_titles(1)]
            self.cache.validate()
        return self._children


class All(Directory, Item):

    def __init__(self, quality: str, cache: CacheControl):
        Directory.__init__(self, 'all', [])
        self.cache = cache
        Item.__init__(self)
        self.quality = quality

    @property
    def children(self):
        if not self.cache.is_valid():
            self._children = [Page(p, self.quality, CacheControl(6000)) for p in self.reader.get_pages()]
            self.cache.validate()
        return self._children


class Page(Directory, Item):

    def __init__(self, page, quality: str, cache: CacheControl):
        Directory.__init__(self, page, [])
        self.cache = cache
        Item.__init__(self)
        self.page = int(page)
        self.quality = quality

    @property
    def children(self):
        if not self.cache.is_valid():
            self._children = [Title(t, self.quality, CacheControl(6000)) for t in self.reader.get_titles(self.page)]
            self.cache.validate()
        return self._children


class Title(Directory, Item):

    def __init__(self, title, quality: str, cache: CacheControl):
        Directory.__init__(self, title['title'], [])
        self.cache = cache
        Item.__init__(self)
        self.title = title
        self.quality = quality

    @property
    def children(self):
        if not self.cache.is_valid():
            series = self.reader.get_series(self.title['id'])
            num = 0
            self._children = []
            for episode in series[self.quality]:
                self._children.append(Playlist(episode.title, series[self.quality][num:]))
                num += 1
            self.cache.validate()
        return self._children


class Playlist(File, Item):

    def __init__(self, title, records):
        File.__init__(self, "%s.m3u8" % title)
        self.records = records
        self.title = title

    @property
    def content(self):
        return "#EXTM3U\n" + "\n".join(str(s) for s in self.records)


class Record():

    def __init__(self, title, url):
        self.title = title
        self.url = url

    def __str__(self):
        return "#EXTINF:-1, %(title)s\n%(url)s\n" % {'url': self.url, 'title': self.title}

    def __lt__(self, other):
        self_split = self.title.split(' ')[0]
        other_split = other.title.split(' ')[0]
        try:
            self_num = int(self_split)
        except ValueError:
            try:
                int(other_split)
            except ValueError:
                return self.title < other.title
            return False
        try:
            other_num = int(other_split)
        except ValueError:
            return True
        return int(self_num) < int(other_num)


if __name__ == '__main__':
    import argparse
    from sitefs import mount, parse_options

    parser = argparse.ArgumentParser()
    parser.add_argument('name', type=str, help='FS name, needed for fstab')
    parser.add_argument('path', type=str, help='Target path')
    parser.add_argument('-i', '--interactive', help='Start in interactive mode', action='store_true')
    parser.add_argument('-o', '--options', help='Mount options', default='')

    arguments = parser.parse_args()
    options = parse_options(arguments.options)
    options.setdefault('fsname', arguments.name)
    options.setdefault('foreground', arguments.interactive)
    options.setdefault('quality', 'hd')

    root = Root(options['quality'])
    del options['quality']
    mount(root, arguments.path, **options)
