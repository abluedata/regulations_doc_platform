<script setup lang="ts">
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'

const props = withDefaults(defineProps<{
  content: string
  source?: 'markdown' | 'html'
}>(), {
  source: 'markdown',
})

marked.setOptions({ breaks: true, gfm: true })

const html = computed(() => {
  const raw = props.source === 'html'
    ? props.content || ''
    : marked.parse(props.content || '') as string
  const sanitized = DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: ['a', 'blockquote', 'br', 'code', 'del', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'li', 'ol', 'p', 'pre', 'span', 'strong', 'table', 'tbody', 'td', 'th', 'thead', 'tr', 'ul'],
    ALLOWED_ATTR: ['class', 'colspan', 'href', 'rel', 'rowspan', 'target', 'title'],
    ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|[^a-z]|[a-z+.-]+(?:[^a-z+.-:]|$))/i,
  })
  // DOMPurify is authoritative in browsers; this small allowlist pass also
  // keeps rendered output safe in DOM shims used by component tests.
  const allowedTags = new Set(['A', 'BLOCKQUOTE', 'BR', 'CODE', 'DEL', 'EM', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'HR', 'LI', 'OL', 'P', 'PRE', 'SPAN', 'STRONG', 'TABLE', 'TBODY', 'TD', 'TH', 'THEAD', 'TR', 'UL'])
  const allowedAttrs = new Set(['class', 'colspan', 'href', 'rel', 'rowspan', 'target', 'title'])
  const template = document.createElement('template')
  template.innerHTML = sanitized
  for (const element of Array.from(template.content.querySelectorAll('*'))) {
    if (!allowedTags.has(element.tagName)) {
      element.replaceWith(document.createTextNode(element.textContent || ''))
      continue
    }
    for (const attribute of Array.from(element.attributes)) {
      if (!allowedAttrs.has(attribute.name.toLowerCase())) element.removeAttribute(attribute.name)
    }
    const href = element.getAttribute('href')
    if (href && !/^(https?:|mailto:|#|\/)/i.test(href)) element.removeAttribute('href')
  }
  return template.innerHTML
})
</script>

<template>
  <div class="safe-markdown" v-html="html" />
</template>
