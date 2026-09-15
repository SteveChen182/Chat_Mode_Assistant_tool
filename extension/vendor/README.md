# Web Chat Rendering Dependencies

Pinned browser distributions are bundled locally for Manifest V3. The extension
does not load executable scripts from a CDN at runtime.

| Dependency | Version | Distribution | License |
| --- | --- | --- | --- |
| marked | 15.0.12 | marked.umd.js | marked-LICENSE.md |
| DOMPurify | 3.3.1 | purify.min.js | dompurify-LICENSE |

Release sources:

- https://unpkg.com/marked@15.0.12/lib/marked.umd.js
- https://unpkg.com/dompurify@3.3.1/dist/purify.min.js

The web chat parses Markdown with marked and sanitizes it with DOMPurify before
insertion. The allowed elements exclude scripts, images, forms, SVG and embedded
content. Links are restricted to HTTP and HTTPS. HTML exports use the same
rendering path and a restrictive content security policy.

To update, replace the pinned browser distributions and corresponding licenses
together, then update the versions documented here. Application-specific rendering
options remain in webchat.js, not in the vendor files.