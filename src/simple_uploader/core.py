"""Config and streaming S3 SigV4 uploads; Python standard library only."""
import datetime as dt
import hashlib
import hmac
import mimetypes
import os
from pathlib import Path
import shlex
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass


class UploaderError(Exception):
    pass


FIELDS = (
    ('S3_ENDPOINT', 'Endpoint URL', ''),
    ('S3_BUCKET', 'Bucket name', ''),
    ('S3_REGION', 'Region', 'auto'),
    ('S3_ACCESS_KEY_ID', 'Access key ID', ''),
    ('S3_SECRET_ACCESS_KEY', 'Secret access key', ''),
    ('S3_PATH_PREFIX', 'Path prefix', 'uploads/'),
    ('S3_PUBLIC_URL_BASE', 'Public URL base (custom domain / CDN)', ''),
    ('S3_ACL', 'ACL (blank for R2; public-read for S3)', ''),
    ('S3_SESSION_TOKEN', 'Session token (optional)', ''),
)
REQUIRED = ('S3_ENDPOINT', 'S3_BUCKET', 'S3_ACCESS_KEY_ID', 'S3_SECRET_ACCESS_KEY')


def config_path(explicit=None):
    if explicit:
        return Path(explicit).expanduser()
    base = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    own = base / 'simple-uploader/s3.conf'
    shared = base / 'capture/s3.conf'
    return own if own.exists() or not shared.exists() else shared


def read_config(path):
    cfg = {}
    if not path.exists():
        return cfg
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, sep, value = line.partition('=')
        if not sep or not key.strip().startswith('S3_'):
            raise UploaderError(f'Invalid config at {path}:{number}')
        try:
            # Parse shell-style quotes without executing or expanding anything.
            parts = shlex.split(value, comments=True)
        except ValueError as exc:
            raise UploaderError(f'Invalid quoting at {path}:{number}') from exc
        cfg[key.strip()] = ' '.join(parts)
    return cfg


def validate_config(cfg):
    missing = [key for key in REQUIRED if not cfg.get(key)]
    if missing:
        raise UploaderError('Missing config: ' + ', '.join(missing))
    for key in ('S3_ENDPOINT', 'S3_PUBLIC_URL_BASE'):
        if not cfg.get(key):
            continue
        try:
            parsed = urllib.parse.urlsplit(cfg[key])
            valid = (parsed.scheme in ('http', 'https') and parsed.hostname
                     and not parsed.username and not parsed.password
                     and not parsed.query and not parsed.fragment)
            parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise UploaderError(f'{key} must be an http(s) URL without credentials, query, or fragment.')
    if '/' in cfg['S3_BUCKET'] or any(c in cfg['S3_BUCKET'] for c in '\r\n'):
        raise UploaderError('S3_BUCKET must be a bucket name, without slashes.')
    if any('\n' in value or '\r' in value for value in cfg.values()):
        raise UploaderError('Config values must be single lines.')


def write_config(path, cfg):
    validate_config(cfg)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.s3-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write('# simple-uploader: S3 / R2 / B2 / MinIO\n')
            for key, _, default in FIELDS:
                stream.write(f'{key}={shlex.quote(cfg.get(key, default))}\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def mime_for_name(name):
    overrides = {'.md': 'text/markdown', '.markdown': 'text/markdown', '.mkv': 'video/x-matroska'}
    return overrides.get(Path(name).suffix.lower()) or mimetypes.guess_type(name)[0] or 'application/octet-stream'


@dataclass
class Item:
    path: Path
    name: str
    content_type: str

    @property
    def size(self):
        return self.path.stat().st_size


def readable_size(size):
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if size < 1024 or unit == 'GiB':
            return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024


def object_key(cfg, name):
    prefix = cfg.get('S3_PATH_PREFIX', '').strip('/')
    clean = Path(name).name.replace('\r', '_').replace('\n', '_') or 'clipboard.bin'
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')
    unique = f'{stamp}-{uuid.uuid4().hex[:12]}-{clean}'
    return f'{prefix}/{unique}' if prefix else unique


def sign_request(cfg, item, key, now=None):
    """Return the signed request and public URL, streaming the supplied file."""
    validate_config(cfg)
    digest = hashlib.sha256()
    with item.path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    payload_hash = digest.hexdigest()
    endpoint = urllib.parse.urlsplit(cfg['S3_ENDPOINT'].rstrip('/'))
    # Decode existing endpoint escapes once, then encode the entire canonical path.
    path = urllib.parse.unquote(endpoint.path).rstrip('/') + '/' + cfg['S3_BUCKET'] + '/' + key
    canonical_uri = urllib.parse.quote(path, safe='/~')
    upload_url = urllib.parse.urlunsplit((endpoint.scheme, endpoint.netloc, canonical_uri, '', ''))
    now = now or dt.datetime.now(dt.timezone.utc)
    date, timestamp = now.strftime('%Y%m%d'), now.strftime('%Y%m%dT%H%M%SZ')
    region = cfg.get('S3_REGION') or 'auto'
    headers = {
        'host': endpoint.netloc,
        'content-type': item.content_type,
        'content-length': str(item.size),
        'x-amz-content-sha256': payload_hash,
        'x-amz-date': timestamp,
    }
    if cfg.get('S3_ACL'):
        headers['x-amz-acl'] = cfg['S3_ACL']
    if cfg.get('S3_SESSION_TOKEN'):
        headers['x-amz-security-token'] = cfg['S3_SESSION_TOKEN']
    names = sorted(headers)
    signed_headers = ';'.join(names)
    canonical_headers = ''.join(f'{name}:{" ".join(headers[name].split())}\n' for name in names)
    canonical_request = '\n'.join(('PUT', canonical_uri, '', canonical_headers, signed_headers, payload_hash))
    scope = f'{date}/{region}/s3/aws4_request'
    string_to_sign = '\n'.join(('AWS4-HMAC-SHA256', timestamp, scope,
                                hashlib.sha256(canonical_request.encode()).hexdigest()))
    signing_key = ('AWS4' + cfg['S3_SECRET_ACCESS_KEY']).encode()
    for value in (date, region, 's3', 'aws4_request'):
        signing_key = hmac.new(signing_key, value.encode(), hashlib.sha256).digest()
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers['Authorization'] = (f'AWS4-HMAC-SHA256 Credential={cfg["S3_ACCESS_KEY_ID"]}/{scope}, '
                                f'SignedHeaders={signed_headers}, Signature={signature}')
    public = cfg.get('S3_PUBLIC_URL_BASE', '').rstrip('/')
    url = public + '/' + urllib.parse.quote(key, safe='/~') if public else upload_url
    request = urllib.request.Request(upload_url, method='PUT', headers=headers)
    return request, url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def upload(cfg, item, key=None):
    if item.size > 5 * 1024 ** 3:
        raise UploaderError(f'{item.name} exceeds the 5 GiB single-upload limit.')
    request, url = sign_request(cfg, item, key or object_key(cfg, item.name))
    try:
        with item.path.open('rb') as stream:
            request.data = stream
            # Request.data clears Content-Length; restore it for a signed, non-chunked PUT.
            request.add_header('Content-Length', str(item.size))
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=120) as response:
                response.read(4096)
    except urllib.error.HTTPError as exc:
        detail = ''
        try:
            root = ET.fromstring(exc.read(8192))
            detail = next((node.text for node in root.iter() if node.tag.split('}')[-1] == 'Message'), '')
        except (ET.ParseError, OSError):
            pass
        raise UploaderError(f'Upload failed (HTTP {exc.code})' + (f': {detail}' if detail else '.')
                            + ' Check the endpoint, region, credentials, and bucket permissions.') from exc
    except (OSError, urllib.error.URLError) as exc:
        raise UploaderError(f'Upload failed: {exc}') from exc
    return url
