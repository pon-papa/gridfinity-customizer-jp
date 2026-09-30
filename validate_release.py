from pathlib import Path
import ast, json, zipfile

ROOT = Path(__file__).resolve().parent
TEXT_UTF8 = {'.py', '.json', '.toml', '.md', '.txt', '.html'}

def main():
    errors = []
    for p in ROOT.rglob('*'):
        rel = p.relative_to(ROOT).as_posix()
        try:
            rel.encode('ascii')
        except UnicodeEncodeError:
            errors.append(f'non-ASCII path: {rel}')
        if not p.is_file():
            continue
        if p.suffix.lower() == '.bat':
            b = p.read_bytes()
            if b.startswith(b'\xef\xbb\xbf') or any(x >= 128 for x in b):
                errors.append(f'BAT is not ASCII/BOM-free: {rel}')
            if b'\n' in b.replace(b'\r\n', b''):
                errors.append(f'BAT has non-CRLF newline: {rel}')
        elif p.suffix.lower() in TEXT_UTF8:
            try:
                text = p.read_text('utf-8')
            except UnicodeDecodeError:
                errors.append(f'not UTF-8: {rel}')
                continue
            if p.suffix.lower() == '.py':
                try: ast.parse(text, filename=rel)
                except SyntaxError as e: errors.append(f'Python syntax: {rel}: {e}')
            if p.suffix.lower() == '.json':
                try: json.loads(text)
                except Exception as e: errors.append(f'JSON syntax: {rel}: {e}')
            if any(x in text for x in ('\u7e67', '\u7e3a', '\u8700', '\u8b41')):
                errors.append(f'possible mojibake in text: {rel}')
        elif p.suffix.lower() == '.3mf':
            try:
                with zipfile.ZipFile(p) as z:
                    if '3D/3dmodel.model' not in z.namelist():
                        errors.append(f'3MF missing main model: {rel}')
            except Exception as e:
                errors.append(f'bad 3MF: {rel}: {e}')
    if errors:
        print('\n'.join(errors))
        return 1
    print('Release encoding and structure audit: OK')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
