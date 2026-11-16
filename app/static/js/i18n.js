// i18n.js: the interface is English only. Other scripts call I18N.t() on text they build and send
// I18N.lang with API requests, so this keeps that small surface: t() returns the text unchanged.
const I18N = Object.freeze({ es: false, lang: "en", t: (s) => s });
