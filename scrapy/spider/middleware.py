"""
This module implements the Spider Middleware manager. For more information see
the Spider Middleware doc in:

docs/topics/spider-middleware.rst

"""

from scrapy import log
from scrapy.core.exceptions import NotConfigured
from scrapy.utils.misc import load_object, arg_to_iter
from scrapy.utils.defer import mustbe_deferred, defer_result
from scrapy.utils.middleware import build_middleware_list
from scrapy.http import Request
from scrapy.conf import settings

def _isiterable(possible_iterator):
    return hasattr(possible_iterator, '__iter__')

class SpiderMiddlewareManager(object):
    def __init__(self):
        self.loaded = False
        self.enabled = {}
        self.disabled = {}
        self.spider_middleware = []
        self.result_middleware = []
        self.exception_middleware = []
        self.load()

    def _add_middleware(self, mw):
        if hasattr(mw, 'process_spider_input'):
            self.spider_middleware.append(mw.process_spider_input)
        if hasattr(mw, 'process_spider_output'):
            self.result_middleware.insert(0, mw.process_spider_output)
        if hasattr(mw, 'process_spider_exception'):
            self.exception_middleware.insert(0, mw.process_spider_exception)

    def load(self):
        """Load middleware defined in settings module"""
        mwlist = build_middleware_list(settings['SPIDER_MIDDLEWARES_BASE'],
                                       settings['SPIDER_MIDDLEWARES'])
        self.enabled.clear()
        self.disabled.clear()
        for mwpath in mwlist:
            try:
                cls = load_object(mwpath)
                mw = cls()
                self.enabled[cls.__name__] = mw
                self._add_middleware(mw)
            except NotConfigured, e:
                self.disabled[cls.__name__] = mwpath
                if e.args:
                    log.msg(e)
        log.msg("Enabled spider middlewares: %s" % ", ".join(self.enabled.keys()), \
            level=log.DEBUG)
        self.loaded = True

    def scrape(self, request, response, spider):
        fname = lambda f:'%s.%s' % (f.im_self.__class__.__name__, f.im_func.__name__)

        def process_spider_input(response):
            for method in self.spider_middleware:
                result = method(response=response, spider=spider)
                assert result is None or _isiterable(result), \
                    'Middleware %s must returns None or an iterable object, got %s ' % \
                    (fname(method), type(result))
                if result is not None:
                    return result
            return self.call(request, response, spider)

        def process_spider_exception(_failure):
            exception = _failure.value
            for method in self.exception_middleware:
                result = method(response=response, exception=exception, spider=spider)
                assert result is None or _isiterable(result), \
                    'Middleware %s must returns None, or an iterable object, got %s ' % \
                    (fname(method), type(result))
                if result is not None:
                    return result
            return _failure

        def process_spider_output(result):
            for method in self.result_middleware:
                result = method(response=response, result=result, spider=spider)
                assert _isiterable(result), \
                    'Middleware %s must returns an iterable object, got %s ' % \
                    (fname(method), type(result))

            return self._validate_output(request, result, spider)

        dfd = mustbe_deferred(process_spider_input, response)
        dfd.addErrback(process_spider_exception)
        dfd.addCallback(process_spider_output)
        return dfd

    def call(self, request, result, spider):
        defer_result(result).chainDeferred(request.deferred)
        request.deferred.addCallback(arg_to_iter)
        return request.deferred

    def _validate_output(self, request, result, spider):
        """Every request returned by spiders must be instanciate with a callback"""
        for r in result:
            if isinstance(r, Request) and not r.deferred.callbacks:
                log.msg('Ignoring %s returned from spider while processing %s: ' \
                        'Request has no callback, try adding callback=self.parse ' \
                        'argument when instanciating Request objects inside your spiders' \
                        % (r, request), level=log.WARNING, domain=spider.domain_name)
                continue
            yield r


