import Prism from 'prismjs/components/prism-core.js';
import 'prismjs/components/prism-clike.js';
import 'prismjs/components/prism-c.js';
import 'prismjs/components/prism-toml.js';
import 'prismjs/components/prism-bash.js';
import 'prismjs/components/prism-protobuf.js';

// Tokenize the whole document so multiline strings/comments retain their state.
// Return React text segments instead of injecting highlighter HTML.
export function highlightLines(source, language) {
  const grammar = Prism.languages[language];
  const lines = [[]];
  function append(value, classes = []) {
    if (Array.isArray(value)) {
      value.forEach(token => append(token, classes));
    } else if (typeof value === 'string') {
      value.split('\n').forEach((text, index) => {
        if (index) lines.push([]);
        if (text) lines.at(-1).push({text, classes});
      });
    } else {
      append(value.content, [value.type, ...[].concat(value.alias || [])]);
    }
  }
  append(grammar ? Prism.tokenize(source, grammar) : source);
  return lines;
}
