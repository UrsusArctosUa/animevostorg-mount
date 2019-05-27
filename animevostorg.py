#!/usr/bin/env python3

'''
Created on Oct 30, 2018

@author: Dmytro Dubrovny <dubrovnyd@gmail.com>
'''
from sitefs import RootDirectory, Directory, File, CacheControl, sanitize_filename
import requests
import json


class Reader(object):

    def __init__(self):
        self.api_url = 'https://api.animevost.org/v1'
        self.quantity = 24

    def list_latest(self):
        page = requests.get("%s/last?page=1&quantity=1" % (self.api_url))
        series = json.loads(page.text)
        index = 0
        max_page = series['state']['count'] // self.quantity + 1
        return ["%03d" % page for page in range(1, max_page)]

    def list_titles(self, page):
        page = requests.get("%s/last?page=%d&quantity=%d" % (self.api_url, page, self.quantity))
        series = json.loads(page.text)
        index = 0
        for s in series['data']:
            index += 1
            title = {'title': "%02d %s" % (index, sanitize_filename(s['title'])), 'id': s['id']}
            yield title

    def list_series(self, title_id):
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


class Root(RootDirectory):

    def __init__(self, quality):
        RootDirectory.__init__(self)
        self.quality = quality
        self.children = [Latest(quality)]


class Latest(Directory, CacheControl, Item):

    def __init__(self, quality, ttl=300):
        Directory.__init__(self, 'latest')
        CacheControl.__init__(self, ttl)
        Item.__init__(self)
        self.quality = quality

    def get_children(self):
        if not self.is_cached():
            self.children = [Page(p, self.quality) for p in self.reader.list_latest()]
            self.validate_cache()
        return self.children


class Page(Directory, CacheControl, Item):

    def __init__(self, page, quality, ttl=300):
        Directory.__init__(self, page)
        CacheControl.__init__(self, ttl)
        Item.__init__(self)
        self.page = int(page)
        self.quality = quality

    def get_children(self):
        if not self.is_cached():
            self.children = [Title(t, self.quality)
                             for t in self.reader.list_titles(self.page)]
            self.validate_cache()
        return self.children


class Title(Directory, CacheControl, Item):

    def __init__(self, title, quality, ttl=60):
        Directory.__init__(self, title['title'])
        CacheControl.__init__(self, ttl)
        Item.__init__(self)
        self.title = title
        self.quality = quality

    def get_children(self):
        if not self.is_cached():
            series = self.reader.list_series(self.title['id'])
            num = 0
            for episode in series[self.quality]:
                self.children.append(Playlist(episode.title, series[self.quality][num:]))
                num += 1
            self.validate_cache()
        return self.children


class Playlist(File, Item):

    def __init__(self, title, records):
        File.__init__(self, "%s.m3u8" % title)
        self.records = records
        self.title = title

    def get_content(self):
        return str.encode("#EXTM3U\n" + "\n".join(str(s) for s in self.records))


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
    parser.add_argument('target', type=str, help='Target path')
    parser.add_argument('-i', '--interactive', help='Start in interactive mode', action='store_true')
    parser.add_argument('-o', '--options', help='Mount options')

    arguments = parser.parse_args()
    options = parse_options(arguments.options)
    options.setdefault('fsname', 'animevostorg')
    options.setdefault('foreground', arguments.interactive)

    root = Root(options['quality'])
    del options['quality']
    mount(root, arguments.target, **options)
