import gocept.httpserverlayer.custom
import lxml.objectify
import pysolr
import time
import unittest
import zeit.solr.connection


class RequestHandler(gocept.httpserverlayer.custom.RequestHandler):

    response_code = 200
    response_body = ''
    reason = None
    posts_received = []
    sleep = 0

    def do_POST(self):
        length = int(self.headers['content-length'])
        self.posts_received.append(dict(
            path=self.path,
            data=self.rfile.read(length),
            headers=self.headers,
        ))
        time.sleep(self.sleep)
        self.send_response(self.response_code)
        if self.reason:
            self.send_header('Reason', self.reason)
        self.end_headers()
        self.wfile.write(self.response_body)


HTTP_LAYER = gocept.httpserverlayer.custom.Layer(
    RequestHandler, name='HTTPLayer', module=__name__)


class TestSolrConnection(unittest.TestCase):

    layer = HTTP_LAYER

    def setUp(self):
        super(TestSolrConnection, self).setUp()
        self.solr = zeit.solr.connection.SolrConnection(
            'http://%s/solr/' % self.layer['http_address'])
        self.data = lxml.objectify.XML('<foo/>')

    def tearDown(self):
        RequestHandler.posts_received[:] = []
        RequestHandler.response_code = 200
        RequestHandler.response_body = ''
        RequestHandler.reason = None
        RequestHandler.sleep = 0
        super(TestSolrConnection, self).tearDown()

    def test_update_raw(self):
        self.solr.update_raw(self.data)
        self.assertEquals(1, len(RequestHandler.posts_received))
        post = RequestHandler.posts_received
        self.assertEquals('/solr/update/', post[0]['path'])
        self.assertEquals("<?xml version='1.0' encoding='UTF-8'?>\n<foo/>",
                          post[0]['data'])
        self.assertEquals('text/xml', post[0]['headers']['Content-Type'])

    def test_update_raw_with_error(self):
        RequestHandler.response_code = 500
        RequestHandler.response_body = (
            "<html><body><h1>Failed for some reason</h1> bla"
            "<hr></body></html>")
        RequestHandler.reason = 'Failed for a reason'
        try:
            self.solr.update_raw(self.data)
        except pysolr.SolrError, e:
            self.assertEquals('[Reason: Failed for a reason]', e.args[0])
        else:
            self.fail("Exception not raised")
        self.assertEquals(1, len(RequestHandler.posts_received))

    def test_update_raw_with_error_and_strange_html(self):
        RequestHandler.response_code = 500
        RequestHandler.response_body = "this is not html & broken"
        try:
            self.solr.update_raw(self.data)
        except pysolr.SolrError, e:
            self.assertEquals(
                '[Reason: None]\nthis is not html & broken',
                e.args[0])
        else:
            self.fail("Exception not raised")
        self.assertEquals(1, len(RequestHandler.posts_received))

    def test_delete_escapes_xml(self):
        self.solr.delete(q='foo:a\\&b', commit=False)
        self.assertEquals(1, len(RequestHandler.posts_received))
        post = RequestHandler.posts_received
        self.assertEquals(
            '<delete><query>foo:a\\&amp;b</query></delete>',
            post[0]['data'])

    def test_timeout_should_not_block_indefinitely(self):
        RequestHandler.sleep = 1
        self.solr.timeout = 0.5
        self.assertRaises(pysolr.SolrError,
                          lambda: self.solr.update_raw(self.data))

    def test_search_error_should_not_raise_if_so_configured(self):
        RequestHandler.sleep = 1
        self.solr.timeout = 0.5
        self.solr.ignore_search_errors = True
        # A long query value causes pysolr to POST the query, which matches
        # what our test RequestHandler implements.
        result = self.solr.search('a' * 1024)
        self.assertEqual(0, len(result))
        self.assertEqual([], list(result))
