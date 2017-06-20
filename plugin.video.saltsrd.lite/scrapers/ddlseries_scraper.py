"""
    SALTS XBMC Addon
    Copyright (C) 2014 tknorris

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import re
import log_utils  # @UnusedImport
import kodi
import dom_parser2
from salts_lib import scraper_utils
from salts_lib.constants import FORCE_NO_MATCH
from salts_lib.constants import VIDEO_TYPES
from salts_lib.constants import QUALITIES
from salts_lib.constants import Q_ORDER
import scraper

BASE_URL = 'http://toptvseries.co'
QUALITY_MAP = {'SD-XVID': QUALITIES.MEDIUM, 'DVD9': QUALITIES.HIGH, 'SD-X264': QUALITIES.HIGH,
               'HD-720P': QUALITIES.HD720, 'HD-1080P': QUALITIES.HD1080, '720P': QUALITIES.HD720, 'XVID': QUALITIES.MEDIUM,
               'X264': QUALITIES.HIGH, '1080P': QUALITIES.HD1080}
HEADER_MAP = {'ul.png': 'uploaded.net', 'tb.png': 'turbobit.net', 'utb.png': 'uptobox.com'}

class Scraper(scraper.Scraper):
    base_url = BASE_URL

    def __init__(self, timeout=scraper.DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.base_url = kodi.get_setting('%s-base_url' % (self.get_name()))
        self.max_qorder = 5 - int(kodi.get_setting('%s_quality' % VIDEO_TYPES.EPISODE))

    @classmethod
    def provides(cls):
        return frozenset([VIDEO_TYPES.SEASON, VIDEO_TYPES.EPISODE])

    @classmethod
    def get_name(cls):
        return 'DDLSeries'

    def resolve_link(self, link):
        if 'protect-links' in link:
            html = self._http_get(link, require_debrid=True, cache_limit=0)
            item = dom_parser2.parse_dom(html, 'li')
            if item:
                stream_url = dom_parser2.parse_dom(item[0].content, 'a', req='href')
                if stream_url:
                    return stream_url[0].content
        else:
            return link
    
    def get_sources(self, video):
        source_url = self.get_url(video)
        if not source_url or source_url == FORCE_NO_MATCH: return []
        return self.__get_sources(source_url, video)

    def __get_sources(self, season_url, video):
        hosters = []
        url = scraper_utils.urljoin(self.base_url, season_url)
        html = self._http_get(url, require_debrid=True, cache_limit=.5)
        _part, quality = self.__get_quality(url)
        pattern = '<img[^>]+src="([^"]+)[^>]+alt="[^"]+Download Links"[^>]*>(.*?)(?=<img|</div>)'
        for match in re.finditer(pattern, html, re.I | re.DOTALL):
            image, fragment = match.groups()
            image = image.split('/')[-1]
            host = HEADER_MAP.get(image)
            if not host: continue
            ep_pattern = 'href="([^"]+)[^>]*>\s*Episode\s+0*%s<' % (video.episode)
            for match in re.finditer(ep_pattern, fragment):
                stream_url = match.group(1)
                hoster = {'multi-part': False, 'host': host, 'class': self, 'views': None, 'url': stream_url, 'rating': None, 'quality': quality, 'direct': False}
                hosters.append(hoster)
                
        return hosters
    
    @classmethod
    def get_settings(cls):
        settings = super(cls, cls).get_settings()
        settings = scraper_utils.disable_sub_check(settings)
        return settings

    def _get_episode_url(self, season_url, video):
        if self.__get_sources(season_url, video):
            return season_url
    
    def search(self, video_type, title, year, season=''):  # @UnusedVariable
        try: season = int(season)
        except: season = 0
        
        results = self.__list(title)
        if not results:
            results = self.__search(title, season)

        filtered_results = []
        norm_title = scraper_utils.normalize_title(title)
        for result in results:
            if norm_title in scraper_utils.normalize_title(result['title']) and (not season or season == int(result['season'])):
                result['title'] = '%s - Season %s [%s]' % (result['title'], result['season'], result['q_str'])
                if Q_ORDER[result['quality']] <= self.max_qorder:
                    filtered_results.append(result)

        filtered_results.sort(key=lambda x: Q_ORDER[x['quality']], reverse=True)
        return filtered_results

    def __list(self, title):
        results = []
        params = {'do': 'charmap', 'name': 'tv-series-list', 'args': '/' + title[0]}
        search_url = scraper_utils.urljoin(self.base_url, 'index.php')
        html = self._http_get(search_url, params=params, require_debrid=True, cache_limit=48)
        
        fragment = dom_parser2.parse_dom(html, 'div', {'class': 'downpara-list'})
        if not fragment: return results
        
        for match in dom_parser2.parse_dom(fragment[0].content, 'a', req='href'):
            match_url = match.attrs['href']
            match_title_extra = match.content
            match_title, match_season, q_str, is_pack = self.__get_title_parts(match_title_extra)
            if is_pack: continue
            quality = QUALITY_MAP.get(q_str, QUALITIES.HIGH)
            result = {'url': scraper_utils.pathify_url(match_url), 'title': scraper_utils.cleanse_title(match_title), 'year': '', 'quality': quality,
                      'season': match_season, 'q_str': q_str}
            results.append(result)
        return results

    def __search(self, title, season):
        results = []
        query = '%s season %s' % (title, season)
        data = {'story': query, 'do': 'search', 'subaction': 'search'}
        html = self._http_get(self.base_url + '/', data=data, require_debrid=True, cache_limit=8)
        for _attrs, div in dom_parser2.parse_dom(html, 'div', {'class': 'cover_infos_title'}):
            for attrs, content in dom_parser2.parse_dom(div, 'a', req='href'):
                match_url = attrs['href']
                if '/tv-pack/' in match_url: continue
                match_title, match_season, q_str, is_pack = self.__get_title_parts(content)
                if is_pack: continue
                q_str2, quality = self.__get_quality(match_url)
                if q_str2: q_str = q_str2
                result = {'url': scraper_utils.pathify_url(match_url), 'title': scraper_utils.cleanse_title(match_title), 'year': '',
                          'quality': quality, 'season': match_season, 'q_str': q_str}
                results.append(result)
        
        return results

    def __get_quality(self, match_url):
        for part in match_url.split('/'):
            part = part.upper()
            if part in QUALITY_MAP:
                return part, QUALITY_MAP[part]
        
        return '', QUALITIES.HIGH
    
    def __get_title_parts(self, title):
        title = re.sub('</?[^>]*>', '', title)
        title = title.replace('&nbsp;', ' ')
        match = re.search('(.*?)\s*-?\s*Season\s+(\d+)\s*\[?([^]]+)', title)
        if match:
            match_title, match_season, extra = match.groups()
            extra = extra.upper()
            is_pack = True if '(PACK)' in extra else False
            extra = re.sub('\s*\(PACK\)', '', extra)
            extra = re.sub('\s+', '-', extra)
            return match_title, match_season, extra.upper(), is_pack
        else:
            return title, 0, '', False