import gocept.httpserverlayer.custom
import mock
import plone.testing
import zeit.cms.testing
import zeit.content.article.testing
import zeit.content.volume.testing
import zeit.solr.interfaces
import zeit.workflow.testing
import zope.component
import zope.interface


class RequestHandler(gocept.httpserverlayer.custom.RequestHandler):

    serve = []

    def do_GET(self):
        if self.serve:
            serve = self.serve.pop(0)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(serve)
        else:
            self.send_response(500)
            self.send_header('Reason', 'Nothing to serve for %s' % self.path)
            self.end_headers()

# XXX appending to product config is not very well supported right now
cms_product_config = zeit.cms.testing.cms_product_config.replace(
    '</product-config>', """\
  task-queue-solr events
</product-config>""")


product_config = """\
<product-config zeit.solr>
    solr-url http://localhost:{port}/solr/
</product-config>
"""


class HTTPLayer(gocept.httpserverlayer.custom.Layer):

    def testTearDown(self):
        super(HTTPLayer, self).testTearDown()
        self['request_handler'].serve[:] = []


HTTP_LAYER = HTTPLayer(RequestHandler, module=__name__)


class ZCMLLayer(zeit.cms.testing.ZCMLLayer):

    defaultBases = (HTTP_LAYER,)

    def setUp(self):
        self.product_config = self.product_config.format(
            port=self['http_port'])
        super(ZCMLLayer, self).setUp()


# Prevent confusion with string formatting during product config test setup.
volume_config = zeit.content.volume.testing.product_config
volume_config = volume_config.replace('{', '{{')
volume_config = volume_config.replace('}', '}}')


ZCML_LAYER = ZCMLLayer(
    'ftesting.zcml',
    product_config=cms_product_config +
    zeit.content.article.testing.product_config +
    volume_config +
    zeit.workflow.testing.product_config +
    product_config)


class SolrMockLayer(plone.testing.Layer):

    def setUp(self):
        self['solr'] = mock.Mock()
        zope.interface.alsoProvides(self['solr'], zeit.solr.interfaces.ISolr)
        zope.component.getSiteManager().registerUtility(self['solr'])

    def tearDown(self):
        zope.component.getSiteManager().unregisterUtility(self['solr'])

    def testTearDown(self):
        self['solr'].reset_mock()

SOLR_MOCK_LAYER = SolrMockLayer()


MOCK_ZCML_LAYER = plone.testing.Layer(
    bases=(ZCML_LAYER, SOLR_MOCK_LAYER), name='MockZCMLLayer', module=__name__)


class MockedFunctionalTestCase(zeit.cms.testing.FunctionalTestCase):

    layer = MOCK_ZCML_LAYER

    def setUp(self):
        super(MockedFunctionalTestCase, self).setUp()
        self.solr = self.layer['solr']


class FunctionalTestCase(zeit.cms.testing.FunctionalTestCase):

    layer = ZCML_LAYER

    def setUp(self):
        super(FunctionalTestCase, self).setUp()
        self.solr = zope.component.getUtility(zeit.solr.interfaces.ISolr)
