"""Attach authored source locations to semantic validation errors."""
import re
from pathlib import Path
from micros_tooling.storage.packages import PackageError


class DeclarationError(PackageError):
    code = 'declaration_invalid'

    def __init__(self, path, message):
        self.path = str(Path(path).resolve())
        self.line = None
        # Find the most specific declared path mentioned in the diagnostic.
        candidates = []
        section = ''
        try: lines = Path(path).read_text().splitlines()
        except OSError: lines = []
        for number, text in enumerate(lines, 1):
            table = re.match(r'\s*\[([\w.]+)\]', text)
            assignment = re.match(r'\s*([\w.]+)\s*=', text)
            if table:
                section = table[1]
                key = section
            elif assignment:
                key = (section + '.' if section else '') + assignment[1]
            else: continue
            if key in message: candidates.append((len(key), number))
        if candidates: self.line = max(candidates)[1]
        self.details = dict(path=self.path, line=self.line)
        prefix = self.path + (f':{self.line}' if self.line else '')
        if message.startswith(self.path + ': '): message = message[len(self.path) + 2:]
        super().__init__(f'{prefix}: {message}')


def located(path, error):
    return error if isinstance(error, DeclarationError) else DeclarationError(path, str(error))
