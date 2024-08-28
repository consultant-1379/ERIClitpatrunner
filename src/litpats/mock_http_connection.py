
import json
import re
import StringIO

import cherrypy
from cherrypy._cpreqbody import RequestBody


class MockHTTPResponse(object):
    def __init__(self, text):
        self.text = text

    def read(self):
        return self.text

    @property
    def status(self):
        return cherrypy.response.status


class MockHTTPConnection(object):
    def __init__(self, host):
        self.host = host
        self.response = None

    def _wsgi_environ(self, url):
        return {
            'REQUEST_METHOD': cherrypy.request.method,
            'SERVER_PORT': '9999', 'SERVER_PROTOCOL': 'HTTP/1.1',
            'SERVER_SOFTWARE': 'CherryPy/3.2.2 Server',
            'ACTUAL_SERVER_PROTOCOL': 'HTTP/1.1',
            'HTTP_HOST': 'localhost:9999',
            'PATH_INFO': self._extract_path_info(url),
            'HTTPS': 'on',
            'REQUEST_URI': url,
            'wsgi.multithread': False,
            'QUERY_STRING': self._extract_querystring(url),
            'SSL_CIPHER': 'AES256-SHA',
            'REMOTE_ADDR': '127.0.0.1',
            'HTTP_ACCEPT': '*/*',
            'wsgi.version': (1, 0),
            'SERVER_NAME': '0.0.0.0',
            'wsgi.run_once': False,
            'SSL_PROTOCOL': 'TLSv1/SSLv3',
            'wsgi.multiprocess': False,
            'wsgi.url_scheme': 'https',
            'CONTENT_TYPE': cherrypy.request.headers.get(
                'Content-Type', 'text/plain'),
            'CONTENT_LENGTH': cherrypy.request.headers.get(
                'Content-Length', 0),
        }

    def request(self, method, url, body=None, headers=None):
        cherrypy.serving.request.params = {}
        cherrypy.request.query_string = self._extract_querystring(url)
        cherrypy.request.method = method
        cherrypy.request.headers.update(headers)

        if type(body) is not str:
            str_data = json.dumps(body)
        else:
            str_data = body
        cherrypy.request.headers['Content-Length'] = len(str_data)
        cherrypy.request.body = RequestBody(StringIO.StringIO(str_data),
                                            cherrypy.request.headers)
        cherrypy.request.wsgi_environ = self._wsgi_environ(url)

        cherrypy.serving.request.params.update(
            self._extract_request_params(url))
        path_info = self._extract_path_info(url)

        if headers.get('Content-Type') == 'application/xml':
            self.response = MockHTTPResponse(self._get_xml_response(path_info))
        else:
            self.response = MockHTTPResponse(self._get_response(path_info))

    def _extract_querystring(self, url):
        query_string = ""
        if '?' in url:
            url, query_string = url.split('?', 1)
        return query_string

    def _extract_request_params(self, url):
        query_string = self._extract_querystring(url)
        pairs = query_string.split("&")
        params = dict([pair.split("=") for pair in pairs if "=" in pair])
        return params

    def _extract_url(self, url):
        if '?' in url:
            url, query_string = url.split('?', 1)
        return url

    def _extract_path_info(self, url):
        url = self._extract_url(url)
        if url == 'https://localhost:9999/litp/upgrade':
            return '/litp/upgrade'
        else:
            return re.sub(
                    r'https://localhost:9999/litp(/xml|/rest/v1)?', '', url)

    def getresponse(self):
        return self.response

    def _get_xml_dispatcher(self, full_url):
        app = cherrypy.tree.apps['/litp/xml']
        cherrypy.serving.request.app = app
        return app.config['/']['request.dispatch']

    def _get_dispatcher(self, full_url):
        if full_url == '/litp/upgrade':
            app = cherrypy.tree.apps['/litp/upgrade']
        else:
            app = cherrypy.tree.apps['/litp/rest/v1']
        cherrypy.serving.request.app = app
        return app.config['/']['request.dispatch']

    def _get_xml_response(self, url):
        dispatcher = self._get_xml_dispatcher(self._extract_path_info(url))
        dispatcher(url)
        return cherrypy.request.handler()

    def _get_response(self, url):
        cherrypy.request.path_info = url
        dispatcher = self._get_dispatcher(url)
        dispatcher(url)
        return cherrypy.request.handler()
