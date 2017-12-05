import grokcore.component
import inspect
import lxml.etree
import lxml.objectify
import re
import zeit.cms.interfaces
import zeit.cms.relation.interfaces
import zeit.connector.interfaces
import zeit.content.article.interfaces
import zeit.content.image.interfaces
import zeit.content.volume.interfaces
import zeit.solr.interfaces
import zeit.workflow.interfaces
import zope.component
import zope.dublincore.interfaces
import zope.interface
import zope.publisher.browser
import zope.traversing.interfaces


class GenericXMLContentTextIndex(grokcore.component.Adapter):

    grokcore.component.context(zeit.cms.content.interfaces.IXMLContent)
    grokcore.component.implements(zope.index.text.interfaces.ISearchableText)

    def getSearchableText(self):
        text = self.context.xml.xpath("//text()")
        return [unicode(s) for s in text]


remove_tags_pattern = re.compile(r'<.*?>')


def remove_tags_if_possible(value):
    if isinstance(value, basestring):
        value = remove_tags_pattern.sub('', value)
        value = value.replace('&amp;', '&')
    return value


class Index(object):

    zope.interface.implements(zeit.solr.interfaces.IIndex)

    def __init__(self, interface, attribute, solr=None, filter=lambda x: x,
                 stackup=1):
        self.interface = interface
        self.attribute = attribute
        if solr is None:
            solr = attribute
        self.solr = solr
        self.filter = filter
        solr_mapping = inspect.currentframe(stackup).f_locals.setdefault(
            'solr_mapping', [])
        solr_mapping.append(self)

    def process(self, value, doc_node):
        self.append_to_node(value, doc_node)

    def append_to_node(self, value, parent_node):
        value = self.filter(value)
        if value is None or value == '':
            return
        child_node = lxml.objectify.E.field(value, name=self.solr)
        lxml.objectify.deannotate(child_node)
        parent_node.append(child_node)


class TextIndex(Index):

    def __init__(self, interface, attribute, solr=None, filter=lambda x: x,
                 stackup=1):
        self.interface = interface
        self.attribute = attribute
        if solr is None:
            solr = attribute
        self.solr = solr
        self.filter = filter
        solr_mapping = inspect.currentframe(stackup).f_locals.setdefault(
            'solr_mapping', [])
        solr_mapping.append(self)

    def process(self, value, doc_node):
        super(TextIndex, self).process(' '.join(value()), doc_node)


class RawIndex(Index):

    interface = zope.interface.Interface
    attribute = None

    def __init__(self, interface, tag_name, solr):
        super(RawIndex, self).__init__(
            self.interface, self.attribute, solr, stackup=2)
        self.tag_name = tag_name

    def process(self, value, doc_node):
        try:
            xml = value.xml
        except AttributeError:
            return
        expr = '//' + self.tag_name
        raw = xml.xpath(expr)
        if raw:
            self.append_to_node(
                ''.join(unicode(lxml.etree.tostring(r)) for r in raw),
                doc_node)


class JoinTuple(Index):

    def process(self, value, doc_node):
        self.append_to_node(' '.join(unicode(arg) for arg in value), doc_node)


class SplitTuple(Index):

    def process(self, value, doc_node):
        for arg in value:
            self.append_to_node(unicode(arg), doc_node)


class Channels(Index):

    def process(self, value, doc_node):
        for arg in value:
            self.append_to_node(u' '.join([x for x in arg if x]), doc_node)


class Storystreams(Index):

    def process(self, value, doc_node):
        for arg in value:
            self.append_to_node(arg.id, doc_node)


class Date(Index):

    def process(self, value, doc_node):
        solr_date = str(value).replace(' ', 'T', 1)
        solr_date = solr_date.replace('+00:00', 'Z')
        self.append_to_node(unicode(solr_date), doc_node)


class Keywords(Index):

    def process(self, value, doc_node):
        self.append_to_node(' '.join(unicode(arg.label) for arg in value),
                            doc_node)


class SplitKeywords(Index):

    def process(self, value, doc_node):
        for arg in value:
            self.append_to_node(unicode(arg.label), doc_node)


class SplitReferences(Index):

    def process(self, value, doc_node):
        for arg in value:
            self.append_to_node(arg.uniqueId, doc_node)


class Icon(Index):

    interface = zope.interface.Interface
    attribute = None

    def __init__(self, solr):
        super(Icon, self).__init__(self.interface, self.attribute, solr,
                                   stackup=2)

    def process(self, value, doc_node):
        request = zope.publisher.browser.TestRequest(
            skin=zeit.cms.browser.interfaces.ICMSSkin)
        icon = zope.component.queryMultiAdapter(
            (value, request), name='zmi_icon')
        if icon is None:
            return
        path = icon.url().replace(request['SERVER_URL'], '')
        self.append_to_node(path, doc_node)


class GraphicalPreview(Index):

    interface = zope.interface.Interface
    attribute = None

    def __init__(self, view_name, solr):
        super(GraphicalPreview, self).__init__(
            self.interface, self.attribute, solr, stackup=2)
        self.view_name = view_name

    def process(self, value, doc_node):
        request = zope.publisher.browser.TestRequest(
            skin=zeit.cms.browser.interfaces.ICMSSkin)
        preview = zope.component.queryMultiAdapter(
            (value, request), name=self.view_name)
        if preview is None:
            return
        url = zope.component.getMultiAdapter(
            (preview, request),
            zope.traversing.browser.interfaces.IAbsoluteURL)
        try:
            url = url()
        except TypeError:
            # Insufficient context
            return
        if url.startswith(request['SERVER_URL']):
            url = url.replace(request['SERVER_URL'], '')
        self.append_to_node(url, doc_node)


class ListRepresentationIndex(Index):

    interface = zope.interface.Interface
    attribute = None

    def __init__(self, attribute, solr=None, filter=lambda x: x):
        if solr is None:
            solr = attribute
        super(ListRepresentationIndex, self).__init__(
            self.interface, self.attribute, solr, filter, stackup=2)
        self.list_attribute = attribute

    def process(self, value, doc_node):
        request = zope.publisher.browser.TestRequest(
            skin=zeit.cms.browser.interfaces.ICMSSkin)
        list_repr = zope.component.queryMultiAdapter(
            (value, request), zeit.cms.browser.interfaces.IListRepresentation)
        if list_repr is None:
            return
        value = getattr(list_repr, self.list_attribute)
        self.append_to_node(value, doc_node)


class AccessCounterIndex(Index):

    interface = zeit.cms.content.interfaces.IAccessCounter

    def __init__(self, solr):
        super(AccessCounterIndex, self).__init__(
            self.interface, None, solr, stackup=2)

    def process(self, value, doc_node):
        hits = value.total_hits
        if hits and value.hits:
            hits -= value.hits
        self.append_to_node(hits, doc_node)


class ImageIndex(Index):

    def process(self, value, doc_node):

        if value is None:
            return
        image = zeit.content.image.interfaces.IImageMetadata(value, None)
        if image is None:
            return
        self.append_to_node(unicode(value.uniqueId), doc_node)
        pub = zeit.workflow.interfaces.ITimeBasedPublishing(value, None)
        if pub is not None:
            expires = pub.released_to
        if expires is None:
            expires = ''
        self.append_to_node(unicode(expires), doc_node)
        ref = zope.component.getAdapter(
            value, zeit.cms.content.interfaces.IXMLReference, name='image')
        type = ref.get('type')
        if type is None:
            type = ''
        self.append_to_node(unicode(type), doc_node)


class ImageExpireDate(Date):

    def process(self, value, doc_node):
        if value is None:
            return
        pub = zeit.workflow.interfaces.ITimeBasedPublishing(value, None)
        if pub is not None:
            expires = pub.released_to
        if expires is None:
            expires = ''
        super(ImageExpireDate, self).process(expires, doc_node)


class VolumeIndex(Index):
    # Special case: only apply to IVolume objects and not to other
    # ICMSContent that has been adapted to find their IVolume.

    def process(self, value, doc_node):
        if not zeit.content.volume.interfaces.IVolume.providedBy(value):
            return

        if value.date_digital_published:
            solr_date = str(value.date_digital_published).replace(' ', 'T', 1)
            solr_date = solr_date.replace('+00:00', 'Z')
            self.append_to_node(unicode(solr_date), doc_node)


class SolrConverter(object):
    """Convert content objects to XML data using a Solr schema to feed the Solr
    server.

    """

    zope.component.adapts(zeit.cms.interfaces.ICMSContent)
    zope.interface.implements(zeit.solr.interfaces.ISolrConverter)

    Index(
        zeit.content.image.interfaces.IImageMetadata,
        'alt')
    SplitTuple(
        zeit.cms.content.interfaces.ICommonMetadata,
        'authors')
    SplitReferences(
        zeit.cms.relation.interfaces.IReferences, None,
        solr='referenced')
    JoinTuple(
        zeit.cms.content.interfaces.ICommonMetadata,
        'authors', solr='authors_fulltext')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'breaking_news')
    Index(
        zeit.content.article.interfaces.IBreakingNews,
        'is_breaking')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'commentsAllowed', solr='allow_comments')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'byline')
    Index(
        zeit.content.image.interfaces.IImageMetadata,
        'caption')
    Index(
        zeit.workflow.interfaces.IContentWorkflow,
        'corrected')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'countings')
    Date(
        zeit.cms.workflow.interfaces.IPublishInfo,
        'date_first_released', solr='date-first-released')
    Date(
        zeit.cms.workflow.interfaces.IModified,
        'date_last_modified', solr='date-last-modified')
    Date(
        zeit.cms.workflow.interfaces.IPublishInfo,
        'date_last_published', solr='date-last-published')
    Date(
        zeit.cms.workflow.interfaces.IPublishInfo,
        'date_last_published_semantic', solr='date-last-published-semantic')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'dailyNewsletter', solr='DailyNL')
    Date(
        zope.dublincore.interfaces.IDCPublishing,
        'expires')
    Date(
        zope.dublincore.interfaces.IDCTimes,
        'created')
    Index(
        zeit.content.article.interfaces.IArticleMetadata,
        'has_recensions')
    Index(
        zeit.content.article.interfaces.IArticleMetadata,
        'is_instant_article')
    Index(
        zeit.content.article.interfaces.IArticleMetadata,
        'is_amp')
    Keywords(
        zeit.cms.content.interfaces.ICommonMetadata,
        'keywords')
    SplitKeywords(
        zeit.cms.content.interfaces.ICommonMetadata,
        'keywords', solr='keywords_list')
    Index(
        zeit.cms.workflow.interfaces.IModified,
        'last_modified_by')
    Index(
        zeit.content.image.interfaces.IImageGroup,
        'master_image')
    # first of:
    Date(
        zeit.cms.content.interfaces.ISemanticChange,
        'last_semantic_change', solr='last-semantic-change'),
    Date(
        zope.dublincore.interfaces.IDCTimes,
        'modified', solr='last-semantic-change')
    # /first of
    TextIndex(
        zope.index.text.interfaces.ISearchableText,
        'getSearchableText', solr='main_text')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'page')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'product', solr='product_id', filter=lambda p: p.id)
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'product_text')
    Index(
        zeit.cms.workflow.interfaces.IPublicationStatus,
        'published')
    ImageIndex(
        zeit.content.image.interfaces.IImages,
        'image', solr='image-reference')
    ImageExpireDate(
        zeit.content.image.interfaces.IImages,
        'image', solr='image-expire-date')
    RawIndex(
        zeit.cms.content.interfaces.ICommonMetadata,
        'raw', solr='raw-tags')
    Index(
        zeit.workflow.interfaces.IContentWorkflow,
        'refined')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'ressort')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'serie', filter=lambda s: s.serienname)
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'sub_ressort')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'printRessort', solr='ns-print-ressort')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'subtitle', filter=remove_tags_if_possible)
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'supertitle')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'teaserSupertitle', solr='teaser_supertitle')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'teaserTitle', solr='teaser_title')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'teaserText', solr='teaser_text')
    ListRepresentationIndex(
        'title', filter=remove_tags_if_possible)
    Index(
        zeit.cms.interfaces.ITypeDeclaration,
        'type_identifier', solr='type')
    Index(
        zeit.cms.content.interfaces.IUUID,
        'id', solr='uuid')
    ListRepresentationIndex('volume')
    Index(
        zeit.cms.interfaces.ICMSContent,
        'uniqueId')
    Index(
        zeit.workflow.interfaces.IContentWorkflow,
        'urgent')
    ListRepresentationIndex('year')
    Icon(solr='icon')
    GraphicalPreview('thumbnail', solr='graphical-preview-url')
    GraphicalPreview('preview', solr='graphical-preview-url-large')
    AccessCounterIndex('range')
    Index(
        zeit.cms.content.interfaces.IAccessCounter, 'detail_url',
        solr='range_details')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'lead_candidate')
    Channels(
        zeit.cms.content.interfaces.ICommonMetadata,
        'channels')
    Storystreams(
        zeit.cms.content.interfaces.ICommonMetadata,
        'storystreams')
    Date(
        zeit.cms.content.interfaces.ICommonMetadata,
        'tldr_date')
    VolumeIndex(zeit.cms.interfaces.ICMSContent, None,
                solr='date_digital_published')
    Index(
        zeit.cms.content.interfaces.ICommonMetadata,
        'access')

    def __init__(self, context):
        self.context = context
        self.adapters = {}

    def convert(self):
        self.solr_fields_seen = set()
        root_node = lxml.objectify.E.add()
        doc_node = lxml.objectify.E.doc()
        root_node.append(doc_node)
        indexes = self.solr_mapping + (
            zope.component.getAllUtilitiesRegisteredFor(
                zeit.solr.interfaces.IIndex))
        for index in indexes:
            __traceback_info__ = (self.context, index)
            if index.solr in self.solr_fields_seen:
                continue
            value = self.get_adapter(index.interface)
            if index.attribute is not None:
                value = getattr(value, index.attribute, None)
            if value is None:
                continue
            index.process(value, doc_node)
            self.solr_fields_seen.add(index.solr)

        return root_node

    def get_adapter(self, interface):
        try:
            adapter = self.adapters[interface]
        except KeyError:
            adapter = interface(self.context, None)
            self.adapters[interface] = adapter
        return adapter
