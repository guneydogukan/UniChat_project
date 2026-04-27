"""
UniChat — Windows Encoding Güvenliği

Bu modül ilk import edildiğinde sys.stdout'u UTF-8 destekli
TextIOWrapper ile sarar. Böylece Windows cp1254 konsolunda
emoji ve Türkçe karakterler sorunsuz yazdırılır.

Kullanım:
    import scrapers._encoding_fix   # modül başında, diğer import'lardan önce
"""

import io
import sys

_applied = False

def ensure_utf8_stdout():
    """stdout'u UTF-8 ile sarmalayan tek seferlik fix."""
    global _applied
    if _applied:
        return
    _applied = True

    try:
        # stdout zaten UTF-8 ise dokunma
        if sys.stdout and getattr(sys.stdout, 'encoding', '').lower().replace('-', '') == 'utf8':
            return

        if sys.stdout and hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding='utf-8', errors='replace',
                line_buffering=True,
            )
    except Exception:
        pass

    try:
        if sys.stderr and getattr(sys.stderr, 'encoding', '').lower().replace('-', '') != 'utf8':
            if hasattr(sys.stderr, 'buffer'):
                sys.stderr = io.TextIOWrapper(
                    sys.stderr.buffer, encoding='utf-8', errors='replace',
                    line_buffering=True,
                )
    except Exception:
        pass


# İlk import'ta uygula
ensure_utf8_stdout()
