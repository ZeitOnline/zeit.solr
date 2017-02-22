# coding: utf8
from __future__ import with_statement
from zeit.cms.testcontenttype.testcontenttype import ExampleContentType
import mock
import transaction
import zeit.cms.checkout.helper
import zeit.cms.repository
import zeit.cms.workingcopy.workingcopy
import zeit.solr.testing
import zope.component
import zope.event
import zope.lifecycleevent
import zope.security.management


def checkout_and_checkin():
    repository = zope.component.getUtility(
        zeit.cms.repository.interfaces.IRepository)
    with zeit.cms.checkout.helper.checked_out(repository['testcontent']):
        pass


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
        self.assertTrue(self.solr.update_raw.called)
        self.assert_unique_id('http://xml.zeit.de/t1')

    def test_update_on_checkin(self):
        repository = zope.component.getUtility(
            zeit.cms.repository.interfaces.IRepository)
        with zeit.cms.checkout.helper.checked_out(repository['testcontent']):
            pass
        self.assertTrue(self.solr.update_raw.called)
        self.assert_unique_id('http://xml.zeit.de/testcontent')

    def test_update_should_be_called_in_async(self):
        run_instantly = 'z3c.celery.celery.TransactionAwareTask.run_instantly'
        run_asynchronously = (
            'z3c.celery.celery.TransactionAwareTask.run_asynchronously')
        with mock.patch(run_instantly, return_value=False), \
                mock.patch(run_asynchronously, return_value=False):
            checkout_and_checkin()
            self.assertFalse(self.solr.update_raw.called)

            zope.security.management.endInteraction()
            transaction.commit()
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
        self.assertFalse(self.solr.update_raw.called)

    def test_removed_event_calls_delete(self):
        content = ExampleContentType()
        content.uniqueId = 'xzy://bla/fasel'
        zope.event.notify(zope.lifecycleevent.ObjectRemovedEvent(content))
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
            icc.assert_called_with('http://xml.zeit.de/testcontent', None)

    def test_do_index_object_should_not_raise_when_object_vanished(self):
        with mock.patch('zeit.cms.interfaces.ICMSContent') as icc:
            with mock.patch('zeit.solr.interfaces.IUpdater') as iu:
                icc.return_value = None
                zeit.solr.update.do_index_object(
                    'http://xml.zeit.de/testcontent')
                self.assertFalse(iu.called)
