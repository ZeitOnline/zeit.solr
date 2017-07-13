from zeit.solr import query as lq
import argparse
import gocept.async
import gocept.runner
import grokcore.component
import logging
import zeit.cms.async
import zeit.cms.checkout.interfaces
import zeit.cms.interfaces
import zeit.cms.repository.interfaces
import zeit.cms.workflow.interfaces
import zeit.cms.workingcopy.interfaces
import zeit.solr.interfaces
import zope.component
import zope.lifecycleevent


log = logging.getLogger(__name__)


@gocept.runner.once(principal=gocept.runner.from_config(
    'zeit.solr', 'index-principal'))
def update_main():
    parser = argparse.ArgumentParser(description='Reindex container in solr')
    parser.add_argument('paths', type=unicode, nargs='+',
                        help='path to reindex')
    parser.add_argument(
        "-p", "--published",
        action="store_true",
        help="only work on published resources")

    args = parser.parse_args()
    for path in args.paths:
        container_id = 'http://xml.zeit.de' + path
        update_container(container_id, args.published)


def update_container(container_id, needs_publish):
    valid_status = ['OK', 'imported', 'importedVHB']
    conn = zope.component.getUtility(zeit.solr.interfaces.ISolr)
    log.info("updating container '%s' on '%s'" % (container_id, conn.url))
    start_container = zeit.cms.interfaces.ICMSContent(container_id)
    stack = [start_container]
    while stack:
        content = stack.pop(0)
        if zeit.cms.repository.interfaces.ICollection.providedBy(content):
            stack.extend(content.values())
        if needs_publish is True:
            pubinfo = zeit.cms.workflow.interfaces.IPublishInfo(content)
            published = pubinfo.published
            status = zeit.workflow.interfaces.IOldCMSStatus(content).status
            if (published is False) and (status not in valid_status):
                continue
        zeit.solr.interfaces.IUpdater(content).update()
    conn.commit()


def get_all_solrs():
    result = []
    for name, solr in zope.component.getUtilitiesFor(
            zeit.solr.interfaces.ISolr):
        result.append(solr)
    return result


class IdUpdater(object):

    zope.component.adapts(basestring)
    zope.interface.implements(zeit.solr.interfaces.IUpdater)

    def __init__(self, context):
        self.context = context

    def update(self, solr=u''):
        try:
            content = zeit.cms.interfaces.ICMSContent(self.context)
        except TypeError:  # id does not exist in repository
            zope.component.getAdapter(
                self.context,
                zeit.solr.interfaces.IUpdater, name='delete').update(solr)
        else:
            zeit.solr.interfaces.IUpdater(content).update(solr)


class ContentUpdater(object):

    zope.component.adapts(zeit.cms.interfaces.ICMSContent)
    zope.interface.implements(zeit.solr.interfaces.IUpdater)

    def __init__(self, context):
        self.context = context

    def update(self, solr=u''):
        # Multiple solrs had a different meaning initially (internal/public).
        # Now there is one primary and (currently) one secondary which are all
        # indexed.
        assert not solr
        solrs = get_all_solrs()
        stack = [self.context]
        while stack:
            content = stack.pop(0)

            log.info("Updating: '%s'", content.uniqueId)
            converter = zeit.solr.interfaces.ISolrConverter(content)
            try:
                # NOTE: It would be nicer to use add(), but then the converter
                # would have to be rewritten not to produce XML anymore (and
                # pysolr would have to learn how to set the boost), so we just
                # push the raw XML here and bypass all the pysolr niceties.
                converted_document = converter.convert()
                for solr in solrs:
                    solr.update_raw(converted_document)
            except zeit.solr.interfaces.SolrError, e:
                log.warning("Solr server returned '%s' while updating %s" %
                            (e, content.uniqueId))
                return None
            else:
                if zeit.cms.repository.interfaces.ICollection.providedBy(
                        content):
                    stack.extend(content.values())


@zope.component.adapter(zeit.cms.interfaces.ICMSContent)
@zope.interface.implementer(zeit.solr.interfaces.IUpdater)
def default_updater(context):
    return zope.component.queryAdapter(
        context, zeit.solr.interfaces.IUpdater, name='update')


class Deleter(object):

    zope.component.adapts(basestring)
    zope.interface.implements(zeit.solr.interfaces.IUpdater)

    def __init__(self, context):
        self.context = context

    def update(self, solr=u''):
        # Note that we cannot use the UUID to delete because we just don't know
        # it. All we have is the uniqueId.
        log.info('Removing %s: %s' % (solr, self.context))
        solrs = get_all_solrs()
        query = lq.field('uniqueId', self.context).encode('UTF-8')
        for solr in solrs:
            solr.delete(q=query, commit=False)


@grokcore.component.subscribe(zope.lifecycleevent.IObjectAddedEvent)
def index_after_add(event):
    # We don't use the "extended" (object, event) method as we are not
    # interested in the events which are dispatched to sublocations.
    context = event.object
    if not zeit.cms.interfaces.ICMSContent.providedBy(context):
        return
    if zeit.cms.repository.interfaces.IRepository.providedBy(context):
        return
    if zeit.cms.workingcopy.interfaces.IWorkingcopy.providedBy(
            event.newParent):
        return
    log.info('AfterAdd: Creating async index job for %s (async=%s)' % (
        context.uniqueId, gocept.async.is_async()))
    do_index_object(context.uniqueId)


@grokcore.component.subscribe(
    zeit.cms.interfaces.ICMSContent,
    zeit.cms.checkout.interfaces.IAfterCheckinEvent)
def index_after_checkin(context, event):
    if event.publishing:
        return
    do_index_object(context.uniqueId)


@grokcore.component.subscribe(
    zeit.cms.interfaces.ICMSContent,
    zeit.cms.workflow.interfaces.IPublishedEvent)
def index_after_checkin(context, event):
    do_index_object(context.uniqueId)


@zeit.cms.async.function(queue='solr')
def do_index_object(unique_id):
    context = zeit.cms.interfaces.ICMSContent(unique_id, None)
    if context is None:
        log.warning('Could not index %s because it does not exist any longer.',
                    unique_id)
    else:
        zeit.solr.interfaces.IUpdater(context).update()


@grokcore.component.subscribe(
    zeit.cms.interfaces.ICMSContent,
    zope.lifecycleevent.IObjectRemovedEvent)
def unindex_on_remove(context, event):
    if zeit.cms.workingcopy.interfaces.IWorkingcopy.providedBy(
            event.oldParent):
        return
    do_unindex_unique_id(context.uniqueId)


@zeit.cms.async.function()
def do_unindex_unique_id(uniqueId):
    zope.component.getAdapter(
        uniqueId, zeit.solr.interfaces.IUpdater, name='delete').update()
