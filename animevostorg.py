#!/usr/bin/env python3

'''
Created on Oct 30, 2018

@author: Dmytro Dubrovny <dubrovnyd@gmail.com>
'''

from sitefs import Directory, Playlist, PlaylistItem
from typing import List, Iterator
from cachetools import cached, TTLCache
import requests, json

API_URL = 'https://api.animevost.org/v1'


class Episode(PlaylistItem):

    def __init__(self, title, url):
        PlaylistItem.__init__(self, title, url)

    def __lt__(self, other: 'Episode'):
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

    @staticmethod
    def qualities() -> List[str]:
        return ['std', 'hd']


class Title:

    def __init__(self, title_id: int, quality: str):
        self.__title_id = title_id
        self.__quality = quality

    def __iter__(self):
        return iter(self.__playlist())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __playlist(self) -> List[Playlist]:
        page = requests.post("%s/playlist" % API_URL, {'id': self.__title_id}, None)
        series_data = json.loads(page.text)
        series = []
        for episode_data in series_data:
            if self.__quality in episode_data and requests.head(episode_data[self.__quality]).ok:
                series.append(Episode(episode_data['name'], episode_data[self.__quality]))
            else:
                for quality in Episode.qualities():
                    if quality in episode_data and requests.head(episode_data[quality]).ok:
                        series.append(Episode(episode_data['name'], episode_data[quality]))
                        break
                pass
        playlist = []
        num = 0
        for episode in sorted(series):
            playlist.append(Playlist(episode.title, series[num:]))
            num += 1
        return playlist


class Page:

    def __init__(self, number: int, quality: str, limit: int = 99):
        self.__number = number
        self.__limit = limit
        self.__quality = quality

    def __iter__(self) -> Iterator[Directory]:
        return iter(self.__titles())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __titles(self) -> List[Directory]:
        page = requests.get("%s/last?page=%d&quantity=%d" % (API_URL, self.__number, self.__limit))
        series = json.loads(page.text)
        index = 0
        titles = []
        for s in series['data']:
            index += 1
            titles.append(Directory("%02d %s" % (index, s['title']), Title(s['id'], self.__quality)))
        return titles


class AllPages:

    def __init__(self, quality: str):
        self.__limit = 99
        self.__quality = quality

    def __iter__(self) -> Iterator[Directory]:
        return iter(self.__pages())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __pages(self) -> List[Directory]:
        page = requests.get("%s/last?page=1&quantity=%d" % (API_URL, self.__limit))
        series = json.loads(page.text)
        if len(series['data']) < self.__limit:
            self.__limit = len(series['data'])
        max_page = series['state']['count'] // self.__limit + 1
        pages = [Directory("%03d" % page, Page(page, self.__quality, self.__limit)) for page in range(1, max_page)]
        return pages


class Root(Directory):

    def __init__(self, quality: str):
        Directory.__init__(self, '', [Directory('latest', Page(1, quality)), Directory('all', AllPages(quality))])


if __name__ == '__main__':
    from sitefs import mount, parse_options, argument_parser

    parser = argument_parser()
    parser.add_argument('quality', type=str, help='Video quality', choices=Episode.qualities())
    parser.add_argument('path', type=str, help='Target path')

    arguments = parser.parse_args()
    options = parse_options(arguments)
    options.setdefault('fsname', "animevostorg_%s" % arguments.quality)

    mount(Root(arguments.quality), arguments.path, **options)
