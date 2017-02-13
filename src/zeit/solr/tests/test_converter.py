import datetime
import mock
import pytz
import unittest
import zeit.solr.testing


class TestGraphicalPreview(zeit.solr.testing.FunctionalTestCase):

    def setUp(self):
        import lxml.objectify
        import zeit.cms.interfaces
        import zeit.solr.converter
        super(TestGraphicalPreview, self).setUp()
        self.index = zeit.solr.converter.GraphicalPreview(
            'thumbnail', 'solr-thumbnail')
        self.image = zeit.cms.interfaces.ICMSContent(
            'http://xml.zeit.de/2006/DSC00109_2.JPG')
        self.xml = lxml.objectify.XML('<a/>')

    def test_url_for_image(self):
        self.index.process(self.image, self.xml)
        self.assertEquals('solr-thumbnail', self.xml.field.get('name'))
        self.assertEquals('/repository/2006/DSC00109_2.JPG/thumbnail',
                          self.xml.field)

    def test_no_url_for_testcontent(self):
        import zeit.cms.interfaces
        content = zeit.cms.interfaces.ICMSContent(
            'http://xml.zeit.de/testcontent')
        self.index.process(content, self.xml)
        self.assertEquals([], self.xml.getchildren())


class TestAccessCounter(unittest.TestCase):

    def setUp(self):
        import lxml.objectify
        import zeit.solr.converter
        self.index = zeit.solr.converter.AccessCounterIndex('nase')
        self.xml = lxml.objectify.XML('<a/>')

    def test_total_hits_should_not_include_todays_hits(self):
        ac = mock.Mock()
        ac.hits = 5
        ac.total_hits = 7
        self.index.process(ac, self.xml)
        self.assertEquals(2, self.xml.field)
        self.assertEquals('nase', self.xml.field.get('name'))

    def test_converter_should_index_access_count(self):
        from zeit.solr.converter import SolrConverter, AccessCounterIndex
        indexes = [index for index in SolrConverter.solr_mapping
                   if isinstance(index, AccessCounterIndex)]
        self.assertEquals(1, len(indexes))


class TestConverter(zeit.solr.testing.FunctionalTestCase):

    def get_content(self):
        from zeit.cms.testcontenttype.testcontenttype import ExampleContentType
        return ExampleContentType()

    def convert(self, content):
        import zeit.solr.interfaces
        converter = zeit.solr.interfaces.ISolrConverter(content)
        return converter.convert()

    def test_lsc_should_fall_back_to_modified(self):
        from zope.dublincore.interfaces import IDCTimes
        content = self.get_content()
        now = datetime.datetime(2011, 1, 2, 3, 4, tzinfo=pytz.UTC)
        IDCTimes(content).modified = now
        xml = self.convert(content)
        self.assertEqual(
            ['2011-01-02T03:04:00Z'],
            xml.xpath('//field[@name="last-semantic-change"]'))

    def test_lsc_should_be_used_if_set(self):
        from zeit.cms.content.interfaces import ISemanticChange
        content = self.get_content()
        now = datetime.datetime(2011, 1, 2, 3, 4, tzinfo=pytz.UTC)
        ISemanticChange(content).last_semantic_change = now
        xml = self.convert(content)
        self.assertEqual(
            ['2011-01-02T03:04:00Z'],
            xml.xpath('//field[@name="last-semantic-change"]'))

    def test_lsc_should_not_be_duplicate_if_both_lsc_and_modified_set(self):
        from zeit.cms.content.interfaces import ISemanticChange
        from zope.dublincore.interfaces import IDCTimes
        content = self.get_content()
        modified = datetime.datetime(2011, 1, 2, 3, 4, tzinfo=pytz.UTC)
        IDCTimes(content).modified = modified
        lsc = datetime.datetime(2010, 12, 13, 14, 15, tzinfo=pytz.UTC)
        ISemanticChange(content).last_semantic_change = lsc
        xml = self.convert(content)
        self.assertEqual(
            ['2010-12-13T14:15:00Z'],
            xml.xpath('//field[@name="last-semantic-change"]'))

    def test_converter_should_not_index_empty_tags(self):
        content = self.get_content()
        xml = self.convert(content)
        self.assertEqual(
            [],
            xml.xpath('//field[@name="year"]'))

    def test_channels_are_indexed_multivalued(self):
        content = self.get_content()
        content.channels = [('International', 'Nahost'),
                            ('Deutschland', 'Meinung')]
        xml = self.convert(content)
        self.assertEqual(
            ['International Nahost', 'Deutschland Meinung'],
            [x.text for x in xml.xpath('//field[@name="channels"]')])

    def test_channel_with_no_subchannel_indexes_just_the_channel(self):
        content = self.get_content()
        content.channels = [('International', None)]
        xml = self.convert(content)
        self.assertEqual(
            'International', xml.xpath('//field[@name="channels"]')[0].text)

    def test_storystreams_are_indexed_multivalued(self):
        content = self.get_content()
        source = zeit.cms.content.sources.StorystreamSource()(content)
        content.storystreams = (source.find('test'), source.find('other'))
        xml = self.convert(content)
        self.assertEqual(
            ['test', 'other'],
            [x.text for x in xml.xpath('//field[@name="storystreams"]')])

    def test_print_ressort_is_indexed(self):
        content = self.get_content()
        content.printRessort = 'Feuilleton'
        xml = self.convert(content)
        self.assertEqual(
            'Feuilleton',
            xml.xpath('//field[@name="ns-print-ressort"]')[0].text)

    def test_volume_is_indexed(self):
        import zeit.content.volume.volume
        volume = zeit.content.volume.volume.Volume()
        volume.uniqueId = 'http://xml.zeit.de/volume'
        volume.year = 2015
        volume.volume = 1
        volume.product = zeit.cms.content.sources.Product(u'ZEI')
        volume.date_digital_published = datetime.datetime(
            2015, 1, 1, 0, 0, tzinfo=pytz.UTC)
        xml = self.convert(volume)
        self.assertEqual('volume', xml.xpath('//field[@name="type"]')[0].text)
        self.assertEqual(
            volume.uniqueId, xml.xpath('//field[@name="uniqueId"]')[0].text)
        self.assertEqual('2015', xml.xpath('//field[@name="year"]')[0].text)
        self.assertEqual('1', xml.xpath('//field[@name="volume"]')[0].text)
        self.assertEqual(
            '2015-01-01T00:00:00Z',
            xml.xpath('//field[@name="date_digital_published"]')[0].text)

    def test_does_not_index_volume_properties_for_articles(self):
        content = self.get_content()
        content.year = 2006
        content.volume = 49
        content.product = zeit.cms.content.sources.Product(u'ZEI')
        self.repository['content'] = content
        volume = zeit.content.volume.volume.Volume()
        volume.year = content.year
        volume.volume = content.volume
        volume.product = content.product
        self.repository['2006']['49']['ausgabe'] = volume

        found = zeit.content.volume.interfaces.IVolume(content)
        self.assertEqual(found, volume)

        xml = self.convert(content)
        self.assertFalse(xml.xpath('//field[@name="date_digital_published"]'))

    def test_relased_to_date_of_teaser_image_is_indexed(self):
        image = zeit.cms.interfaces.ICMSContent(
            'http://xml.zeit.de/2006/DSC00109_2.JPG')
        pub = zeit.cms.workflow.interfaces.IPublishInfo(image)
        pub.released_to = datetime.datetime(2015, 1, 1, 0, 0, tzinfo=pytz.UTC)
        content = self.get_content()
        zeit.content.image.interfaces.IImages(content).image = image

        xml = self.convert(content)
        self.assertEqual(
            '2015-01-01T00:00:00Z',
            xml.xpath('//field[@name="image-expire-date"]')[0].text)
