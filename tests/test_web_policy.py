"""Wikipedia search sends one explicitly confirmed query and treats sources as data."""
import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from modelmate import ProbeError, main, run_wikipedia_search, search_wikipedia


class WebPolicyTests(unittest.TestCase):
    def test_eof_refusal_or_stale_confirmation_never_sends_query(self):
        for confirmation in ('', 'SEARCH deadbeef', 'SEARCH stale\n', 'SEARCH deadbeef extra\n', 'CANCEL\n'):
            with self.subTest(confirmation=confirmation), patch('secrets.token_hex', return_value='deadbeef'):
                with patch('modelmate.search_wikipedia') as transport:
                    output = io.StringIO()
                    self.assertEqual(run_wikipedia_search(io.StringIO('ข้อมูลส่วนตัว\n' + confirmation),
                                                         output, 'th'), 2)
                    self.assertIn('th.wikipedia.org', output.getvalue())
                    transport.assert_not_called()

    def test_confirmed_search_passes_only_the_previewed_query(self):
        with patch('secrets.token_hex', return_value='deadbeef'), patch('modelmate.search_wikipedia',
                return_value=[{'title': 'Source', 'excerpt': 'Public excerpt', 'url': 'https://en.wikipedia.org/?curid=7'}]) as transport:
            output = io.StringIO()
            source = io.StringIO('  sample & text  \n SEARCH deadbeef \t\nprivate history\n')
            self.assertEqual(run_wikipedia_search(source, output, 'en'), 0)
            transport.assert_called_once_with('sample & text', 'en')
            self.assertIn('https://en.wikipedia.org/?curid=7', output.getvalue())

    def test_invalid_utf8_query_can_be_reentered_without_sending_corrupt_input(self):
        source = io.TextIOWrapper(io.BytesIO(b'\xe0\n' + 'ภาษาไพทอน\nSEARCH deadbeef\n'.encode()),
                                  encoding='utf-8')
        with source, patch('secrets.token_hex', return_value='deadbeef'), patch(
                'modelmate.search_wikipedia', return_value=[]) as transport:
            output = io.StringIO()
            self.assertEqual(run_wikipedia_search(source, output, 'th'), 0)
            self.assertIn('คำค้นอ่านเป็น UTF-8 ไม่ได้', output.getvalue())
            transport.assert_called_once_with('ภาษาไพทอน', 'th')

    def test_invalid_confirmation_bytes_do_not_block_preview_or_send_query(self):
        source = io.TextIOWrapper(io.BytesIO(b'Wikipedia\nSEARCH \xe0\n'), encoding='utf-8')
        with source, patch('secrets.token_hex', return_value='deadbeef'), patch(
                'modelmate.search_wikipedia') as transport:
            output = io.StringIO()
            self.assertEqual(run_wikipedia_search(source, output, 'en'), 2)
            self.assertIn('en.wikipedia.org', output.getvalue())
            self.assertIn('รหัสยืนยันอ่านเป็น UTF-8 ไม่ได้', output.getvalue())
            transport.assert_not_called()

    def test_transport_ignores_response_links_and_never_follows_a_redirect(self):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = json.dumps({'pages': [{'id': 7, 'title': 'Sample',
            'excerpt': '<span class="searchmatch">text</span> &amp; detail\u001b',
            'url': 'https://other.invalid/private'}]}).encode()
        with patch('http.client.HTTPSConnection', return_value=connection) as connect:
            results = search_wikipedia('a & b เช้า', 'th')
            connect.assert_called_once_with('th.wikipedia.org', timeout=8)
            method, path = connection.request.call_args.args
            self.assertEqual(method, 'GET')
            self.assertEqual(parse_qs(urlsplit(path).query), {'q': ['a & b เช้า'], 'limit': ['5']})
            self.assertEqual(results, [{'title': 'Sample', 'excerpt': 'text & detail',
                                       'url': 'https://th.wikipedia.org/?curid=7'}])
            response.status = 302
            with self.assertRaisesRegex(ProbeError, 'HTTP 302'):
                search_wikipedia('public', 'th')
            self.assertEqual(connection.request.call_count, 2)

    def test_cli_rejects_use_of_positional_prompt_as_search_query(self):
        with (patch('sys.argv', ['modelmate.py', '--search-wikipedia', 'en', 'private prompt']),
              patch('sys.stderr', new_callable=io.StringIO),
              patch('modelmate.search_wikipedia') as transport):
            with self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code, 2)
            transport.assert_not_called()
