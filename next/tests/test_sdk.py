import unittest
from polaris_platform.sdk import Component

class SDKTests(unittest.TestCase):
    def test_keyword_handlers_and_optional_context(self):
        component = Component()
        context = object()
        publications = []
        class Port:
            def advertise(self):
                publications.append(component.describe())
            def call(self, target, operation, params, context=None):
                return [target, operation, params, context is expected]
        expected = context
        component.start(Port())
        @component.operation('echo', access='read')
        def echo(value, ctx):
            return ctx.call('other', 'get', {'value': value})
        self.assertEqual(component.call('echo', {'value': 5}, context), ['other', 'get', {'value': 5}, True])
        self.assertEqual(publications, [component.describe()])
        self.assertEqual(component.describe()['operations']['echo']['access'], 'read')
