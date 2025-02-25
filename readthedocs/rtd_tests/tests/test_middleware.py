from unittest import mock

from corsheaders.middleware import (
    ACCESS_CONTROL_ALLOW_CREDENTIALS,
    ACCESS_CONTROL_ALLOW_ORIGIN,
    CorsMiddleware,
)
from django.conf import settings
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django_dynamic_fixture import get

from readthedocs.builds.constants import LATEST
from readthedocs.core.middleware import (
    NullCharactersMiddleware,
    ReadTheDocsSessionMiddleware,
)
from readthedocs.projects.constants import PRIVATE, PUBLIC
from readthedocs.projects.models import Domain, Project, ProjectRelationship
from readthedocs.rtd_tests.utils import create_user


@override_settings(
    PUBLIC_DOMAIN='readthedocs.io',
)
class TestCORSMiddleware(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = CorsMiddleware()
        self.url = '/api/v2/search'
        self.owner = create_user(username='owner', password='test')
        self.project = get(
            Project, slug='pip',
            users=[self.owner],
            privacy_level=PUBLIC,
            main_language_project=None,
        )
        self.project.versions.update(privacy_level=PUBLIC)
        self.version = self.project.versions.get(slug=LATEST)
        self.subproject = get(
            Project,
            users=[self.owner],
            privacy_level=PUBLIC,
            main_language_project=None,
        )
        self.subproject.versions.update(privacy_level=PUBLIC)
        self.version_subproject = self.subproject.versions.get(slug=LATEST)
        self.relationship = get(
            ProjectRelationship,
            parent=self.project,
            child=self.subproject,
        )
        self.domain = get(
            Domain,
            domain='my.valid.domain',
            project=self.project,
        )
        self.another_project = get(
            Project,
            privacy_level=PUBLIC,
            slug='another',
        )
        self.another_project.versions.update(privacy_level=PUBLIC)
        self.another_version = self.another_project.versions.get(slug=LATEST)
        self.another_domain = get(
            Domain,
            domain='another.valid.domain',
            project=self.another_project,
        )

    def test_allow_linked_domain_from_public_version(self):
        request = self.factory.get(
            self.url,
            {'project': self.project.slug, 'version': self.version.slug},
            HTTP_ORIGIN='http://my.valid.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

    def test_dont_allow_linked_domain_from_private_version(self):
        self.version.privacy_level = PRIVATE
        self.version.save()
        request = self.factory.get(
            self.url,
            {'project': self.project.slug, 'version': self.version.slug},
            HTTP_ORIGIN='http://my.valid.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertNotIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

    def test_allowed_api_public_version_from_another_domain(self):
        request = self.factory.get(
            self.url,
            {'project': self.project.slug, 'version': self.version.slug},
            HTTP_ORIGIN='http://docs.another.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

        request = self.factory.get(
            self.url,
            {'project': self.project.slug, 'version': self.version.slug},
            HTTP_ORIGIN='http://another.valid.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

    def test_not_allowed_api_private_version_from_another_domain(self):
        self.version.privacy_level = PRIVATE
        self.version.save()
        request = self.factory.get(
            self.url,
            {'project': self.project.slug, 'version': self.version.slug},
            HTTP_ORIGIN='http://docs.another.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertNotIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

        request = self.factory.get(
            self.url,
            {'project': self.project.slug, 'version': self.version.slug},
            HTTP_ORIGIN='http://another.valid.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertNotIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

    def test_valid_subproject(self):
        self.assertTrue(
            Project.objects.filter(
                pk=self.project.pk,
                subprojects__child=self.subproject,
            ).exists(),
        )
        request = self.factory.get(
            self.url,
            {'project': self.project.slug, 'version': self.version.slug},
            HTTP_ORIGIN='http://my.valid.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

    def test_embed_api_private_version_linked_domain(self):
        self.version.privacy_level = PRIVATE
        self.version.save()
        request = self.factory.get(
            '/api/v2/embed/',
            {'project': self.project.slug, 'version': self.version.slug},
            HTTP_ORIGIN='http://my.valid.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertNotIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

    def test_embed_api_external_url(self):
        request = self.factory.get(
            "/api/v2/embed/",
            {"url": "https://pip.readthedocs.io/en/latest/index.hml"},
            HTTP_ORIGIN="http://my.valid.domain",
        )
        resp = self.middleware.process_response(request, {})
        self.assertIn("Access-Control-Allow-Origin", resp)

        request = self.factory.get(
            "/api/v2/embed/",
            {"url": "https://docs.example.com/en/latest/index.hml"},
            HTTP_ORIGIN="http://my.valid.domain",
        )
        resp = self.middleware.process_response(request, {})
        self.assertIn("Access-Control-Allow-Origin", resp)

    @mock.patch('readthedocs.core.signals._has_donate_app')
    def test_sustainability_endpoint_allways_allowed(self, has_donate_app):
        has_donate_app.return_value = True
        request = self.factory.get(
            '/api/v2/sustainability/',
            {'project': self.project.slug, 'active': True, 'version': self.version.slug},
            HTTP_ORIGIN='http://invalid.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

        request = self.factory.get(
            '/api/v2/sustainability/',
            {'project': self.project.slug, 'active': True, 'version': self.version.slug},
            HTTP_ORIGIN='http://my.valid.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

    @mock.patch('readthedocs.core.signals._has_donate_app')
    def test_sustainability_endpoint_no_ext(self, has_donate_app):
        has_donate_app.return_value = False
        request = self.factory.get(
            '/api/v2/sustainability/',
            {'project': self.project.slug, 'active': True, 'version': self.version.slug},
            HTTP_ORIGIN='http://invalid.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertNotIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

        request = self.factory.get(
            '/api/v2/sustainability/',
            {'project': self.project.slug, 'active': True, 'version': self.version.slug},
            HTTP_ORIGIN='http://my.valid.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertNotIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

    def test_apiv2_endpoint_not_allowed(self):
        request = self.factory.get(
            '/api/v2/version/',
            {'project': self.project.slug, 'active': True, 'version': self.version.slug},
            HTTP_ORIGIN='http://invalid.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertNotIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

        # This also doesn't work on registered domains.
        request = self.factory.get(
            '/api/v2/version/',
            {'project': self.project.slug, 'active': True, 'version': self.version.slug},
            HTTP_ORIGIN='http://my.valid.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertNotIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

        # Or from our public domain.
        request = self.factory.get(
            '/api/v2/version/',
            {'project': self.project.slug, 'active': True, 'version': self.version.slug},
            HTTP_ORIGIN='http://docs.readthedocs.io/',
        )
        resp = self.middleware.process_response(request, {})
        self.assertNotIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)

        # POST is not allowed
        request = self.factory.post(
            '/api/v2/version/',
            {'project': self.project.slug, 'active': True, 'version': self.version.slug},
            HTTP_ORIGIN='http://my.valid.domain',
        )
        resp = self.middleware.process_response(request, {})
        self.assertNotIn(ACCESS_CONTROL_ALLOW_ORIGIN, resp)
        self.assertNotIn(ACCESS_CONTROL_ALLOW_CREDENTIALS, resp)


class TestSessionMiddleware(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = ReadTheDocsSessionMiddleware()

        self.user = create_user(username='owner', password='test')

    @override_settings(SESSION_COOKIE_SAMESITE=None)
    def test_fallback_cookie(self):
        request = self.factory.get('/')
        response = HttpResponse()
        self.middleware.process_request(request)
        request.session['test'] = 'value'
        response = self.middleware.process_response(request, response)

        self.assertTrue(settings.SESSION_COOKIE_NAME in response.cookies)
        self.assertTrue(self.middleware.cookie_name_fallback in response.cookies)

    @override_settings(SESSION_COOKIE_SAMESITE=None)
    def test_main_cookie_samesite_none(self):
        request = self.factory.get('/')
        response = HttpResponse()
        self.middleware.process_request(request)
        request.session['test'] = 'value'
        response = self.middleware.process_response(request, response)

        self.assertEqual(response.cookies[settings.SESSION_COOKIE_NAME]['samesite'], 'None')
        self.assertEqual(response.cookies[self.middleware.cookie_name_fallback]['samesite'], '')

    def test_main_cookie_samesite_lax(self):
        request = self.factory.get('/')
        response = HttpResponse()
        self.middleware.process_request(request)
        request.session['test'] = 'value'
        response = self.middleware.process_response(request, response)

        self.assertEqual(response.cookies[settings.SESSION_COOKIE_NAME]['samesite'], 'Lax')
        self.assertTrue(self.test_main_cookie_samesite_none not in response.cookies)


class TestNullCharactersMiddleware(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = NullCharactersMiddleware(None)

    def test_request_with_null_chars(self):
        request = self.factory.get("/?language=en\x00es&project_slug=myproject")
        response = self.middleware(request)
        self.assertContains(
            response,
            "There are NULL (0x00) characters in at least one of the parameters (language) passed to the request.",
            status_code=400,
        )
