#!/usr/bin/env python3

'''
Created on Oct 30, 2018

@author: Dmytro Dubrovny <dubrovnyd@gmail.com>
'''
from sitefs import Directory, Playlist, sanitize_filename
import requests
import json
import time

API_URL = 'https://api.animevost.org/v1'


class Episode(object):

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


class Cached(object):

    def __init__(self, ttl: int):
        self.__ttl = ttl
        self.__updated_at = 0

    def is_valid(self):
        return time.time() - self.__updated_at < self.__ttl

    def validate(self):
        self.__updated_at = time.time()

    def invalidate(self):
        self.__updated_at = 0


class Title(Cached):

    def __init__(self, id: int, quality: str, ttl: int = 3000):
        Cached.__init__(self, ttl)
        self.id = id
        self.quality = quality

    def __iter__(self):
        if not self.is_valid():
            self.__update()

        return iter(self.__playlist)

    def __update(self):
        page = requests.post("%s/playlist" % API_URL, {'id': self.id}, None)
        series = json.loads(page.text)
        std = []
        hd = []
        for item in series:
            if 'std' in item:
                std.append(Episode(item['name'], item['std']))
            if 'hd' in item:
                hd.append(Episode(item['name'], item['hd']))
        self.__series = {'std': sorted(std), 'hd': sorted(hd)}
        self.__playlist = []
        num = 0
        for episode in self.__series[self.quality]:
            self.__playlist.append(Playlist(episode.title, self.__series[self.quality][num:]))
            num += 1
        self.validate()


class Page(Cached):

    def __init__(self, number: int, quality: str, limit: int = 99, ttl: int = 3000):
        Cached.__init__(self, ttl)
        self.number = number
        self.limit = limit
        self.quality = quality

    def __iter__(self):
        if not self.is_valid():
            self.__update()
        return iter(self.__titles)

    def __update(self):
        page = requests.get("%s/last?page=%d&quantity=%d" % (API_URL, self.number, self.limit))
        series = json.loads(page.text)
        index = 0
        self.__titles = []
        for s in series['data']:
            index += 1
            self.__titles.append(
                Directory("%02d %s" % (index, sanitize_filename(s['title'])), Title(s['id'], self.quality)))
        self.validate()


class All(Cached):

    def __init__(self, quality: str, ttl: int = 3000):
        Cached.__init__(self, ttl)
        self.limit = 99
        self.quality = quality

    def __iter__(self):
        if not self.is_valid():
            self.__update()
        return iter(self.__pages)

    def __update(self):
        page = requests.get("%s/last?page=1&quantity=%d" % (API_URL, self.limit))
        series = json.loads(page.text)
        if len(series['data']) < self.limit:
            self.limit = len(series['data'])
        max_page = series['state']['count'] // self.limit + 1
        self.__pages = [Directory("%03d" % page, Page(page, self.quality, self.limit)) for page in range(1, max_page)]
        self.validate()


def make_root(quality):
    return Directory('', [Directory('latest', Page(1, quality)), Directory('all', All(quality))])


if __name__ == '__main__':
    import argparse
    from sitefs import mount, parse_options

    parser = argparse.ArgumentParser()
    parser.add_argument('name', type=str, help='FS name, needed for fstab')
    parser.add_argument('path', type=str, help='Target path')
    parser.add_argument('-i', '--interactive', help='Start in interactive mode', action='store_true')
    parser.add_argument('-o', '--options', help='Mount options', default='')
    parser.add_argument('-q', '--quality', help='Video quality', default='hd')

    arguments = parser.parse_args()
    options = parse_options(arguments.options)
    options.setdefault('fsname', arguments.name)
    options.setdefault('foreground', arguments.interactive)
    options.setdefault('quality', arguments.quality)

    root = make_root(quality=options['quality'])
    del options['quality']
    mount(root, arguments.path, **options)
