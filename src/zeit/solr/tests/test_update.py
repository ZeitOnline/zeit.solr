# coding: utf8

from __future__ import with_statement
from zeit.cms.testcontenttype.testcontenttype import ExampleContentType
from zeit.cms.workflow.interfaces import IPublish, IPublishInfo
import StringIO
import gocept.async
import gocept.async.tests
import logging
import mock
import zeit.cms.checkout.helper
import zeit.cms.repository
import zeit.cms.workingcopy.workingcopy
import zeit.solr.testing
import zope.component
import zope.event
import zope.lifecycleevent


@gocept.async.function(service='events')
def checkout_and_checkin():
    repository = zope.component.getUtility(
        zeit.cms.repository.interfaces.IRepository)
    with zeit.cms.checkout.helper.checked_out(repository['testcontent']):
        pass


def process():
    log_output = StringIO.StringIO()
    log_handler = logging.StreamHandler(log_output)
    logging.root.addHandler(log_handler)
    old_log_level = logging.root.level
    logging.root.setLevel(logging.ERROR)
    try:
        gocept.async.tests.process()
    finally:
        logging.root.removeHandler(log_handler)
        logging.root.setLevel(old_log_level)
    assert not log_output.getvalue(), log_output.getvalue()


class UpdateTest(zeit.solr.testing.MockedFunctionalTestCase):

    def assert_unique_id(self, unique_id):
        xml = self.solr.update_raw.call_args[0][0]
        self.assertEqual(unique_id,
                         xml.xpath('//field[@name="uniqueId"]/text()')[0])

    def test_existing_id_should_be_updated(self):
        zeit.solr.interfaces.IUpdater(
            'http://xml.zeit.de/online/2007/01/Somalia').update()
        self.assertTrue(self.solr.update_raw.called)
        self.assert_unique_id('http://xml.zeit.de/online/2007/01/Somalia')

    def test_nonexistent_id_should_be_deleted(self):
        zeit.solr.interfaces.IUpdater(
            'http://xml.zeit.de/nonexistent').update()
        self.assert_(self.solr.delete.called)
        query = self.solr.delete.call_args[1]
        self.assertEquals({'commit': False,
                           'q': 'uniqueId:(http\\://xml.zeit.de/nonexistent)'},
                          query)

    def test_malformed_id_is_treated_as_delete(self):
        zeit.solr.interfaces.IUpdater('foo').update()
        self.assert_(self.solr.delete.called)

    def test_delete_with_unicode(self):
        zeit.solr.interfaces.IUpdater(
            u'http://xml.zeit.de/nöd-däh').update()
        query = self.solr.delete.call_args[1]
        self.assertEquals(
            {'commit': False,
             'q': 'uniqueId:(http\\://xml.zeit.de/n\xc3\xb6d\\-d\xc3\xa4h)'},
            query)

    def test_update_on_create(self):
        repository = zope.component.getUtility(
            zeit.cms.repository.interfaces.IRepository)
        repository['t1'] = ExampleContentType()
        process()
        self.assertTrue(self.solr.update_raw.called)
        self.assert_unique_id('http://xml.zeit.de/t1')

    def test_update_on_checkin(self):
        repository = zope.component.getUtility(
            zeit.cms.repository.interfaces.IRepository)
        with zeit.cms.checkout.helper.checked_out(repository['testcontent']):
            pass
        process()
        self.assertTrue(self.solr.update_raw.called)
        self.assert_unique_id('http://xml.zeit.de/testcontent')

    def test_update_on_publish(self):
        repository = zope.component.getUtility(
            zeit.cms.repository.interfaces.IRepository)
        IPublishInfo(self.repository['testcontent']).urgent = True
        IPublish(repository['testcontent']).publish(async=False)
        process()
        self.assertTrue(self.solr.update_raw.called)

    def test_update_should_be_called_in_async(self):
        checkout_and_checkin()
        process()
        self.assertTrue(self.solr.update_raw.called)

    def test_recursive(self):
        zeit.solr.interfaces.IUpdater(
            u'http://xml.zeit.de/2007/01').update()
        self.assertTrue(self.solr.update_raw.called)
        # 1 Folder + 40 objects contained in it
        self.assertEquals(41, len(self.solr.update_raw.call_args_list))

    def test_added_event_only_for_events_object(self):
        content = ExampleContentType()
        content.uniqueId = 'xzy://bla/fasel'
        content_sub = ExampleContentType()
        content_sub.uniqueId = 'xzy://bla/fasel/sub'
        event = zope.lifecycleevent.ObjectAddedEvent(content)
        for ignored in zope.component.subscribers((content_sub, event), None):
            pass
        try:
            process()
        except IndexError:
            pass
        self.assertFalse(self.solr.update_raw.called)

    def test_removed_event_calls_delete(self):
        content = ExampleContentType()
        content.uniqueId = 'xzy://bla/fasel'
        zope.event.notify(zope.lifecycleevent.ObjectRemovedEvent(content))
        process()
        query = self.solr.delete.call_args[1]
        self.assertEquals(
            {'q': 'uniqueId:(xzy\\://bla/fasel)', 'commit': False},
            query)

    def test_remove_event_does_not_call_delete_if_parent_is_workingcopy(self):
        content = ExampleContentType()
        content.uniqueId = 'xzy://bla/fasel'
        event = zope.lifecycleevent.ObjectRemovedEvent(content)
        event.oldParent = zeit.cms.workingcopy.workingcopy.Workingcopy()
        zope.event.notify(event)
        try:
            process()
        except IndexError:
            pass
        self.assertFalse(self.solr.delete.called)

    def test_invalid_updater_should_raise_type_error(self):
        updater = zeit.solr.interfaces.IUpdater(
            'http://xml.zeit.de/online/2007/01/Somalia')
        IUpdater = mock.Mock()
        IUpdater().update = mock.Mock(side_effect=TypeError())
        with mock.patch('zeit.solr.interfaces.IUpdater', new=IUpdater):
            self.assertRaises(TypeError, updater.update)

    def test_do_index_object_should_load_object_from_repository(self):
        content = ExampleContentType()
        with mock.patch('zeit.cms.interfaces.ICMSContent') as icc:
            icc.return_value = content
            zeit.solr.update.do_index_object('http://xml.zeit.de/testcontent')
            process()
            icc.assert_called_with('http://xml.zeit.de/testcontent', None)

    def test_do_index_object_should_not_raise_when_object_vanished(self):
        with mock.patch('zeit.cms.interfaces.ICMSContent') as icc:
            with mock.patch('zeit.solr.interfaces.IUpdater') as iu:
                icc.return_value = None
                zeit.solr.update.do_index_object(
                    'http://xml.zeit.de/testcontent')
                process()
                self.assertFalse(iu.called)
