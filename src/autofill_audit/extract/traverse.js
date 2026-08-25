/*
 * The in-page traversal of spec section 9.1.
 *
 * Injected once per frame root and evaluated with one argument, an options
 * object. Returns { nodes, frameElements, seen, truncated }, where `nodes` is
 * plain JSON in document order and `frameElements` is a parallel array of the
 * iframe elements the walk found, so that the caller can turn each one into a
 * frame of its own without querying the document a second time and hoping the
 * order matches.
 *
 * Three ordering rules from spec section 9.1 are implemented here exactly, and
 * changing any of them changes what the extractor means:
 *
 *   1. Open shadow roots are walked IN PLACE, before the host's siblings. The
 *      content of a custom element is visually and semantically between the
 *      fields around it, and the preceding-text signal is only true if the walk
 *      agrees.
 *
 *   2. Iframes are NOTED, not recursed. A cross-origin frame cannot be read,
 *      and recursing in place would mean catching that failure halfway through
 *      a partially built result. Handled as separate roots, one unreadable
 *      frame costs exactly that frame.
 *
 *   3. Closed shadow roots are unreachable from inside the page and no
 *      cleverness changes that. A custom element that has been upgraded,
 *      presents as a control, has no reachable shadow root, and holds no
 *      light-DOM controls is reported as a blind spot rather than as nothing.
 *
 * This file never writes to the document. It reads attributes, computed style,
 * and bounding boxes, and it returns what it read.
 */

(options) => {
  const MAX_OPTIONS = options.maxOptions;
  const MAX_CONTROLS = options.maxControls;
  const MIN_CANVAS_AREA = options.minCanvasArea;
  const FRAMEWORK_ATTRS = options.frameworkAttrs;

  const SKIPPED_INPUT_TYPES = new Set([
    'hidden', 'submit', 'button', 'image', 'reset'
  ]);
  const CONTROL_ROLES = new Set([
    'textbox', 'combobox', 'searchbox', 'spinbutton',
    'checkbox', 'radio', 'switch', 'slider', 'listbox'
  ]);
  const SKIPPED_SUBTREES = new Set([
    'head', 'script', 'style', 'template', 'noscript', 'svg'
  ]);
  const BLOCK_DISPLAYS = new Set([
    'block', 'flex', 'grid', 'list-item', 'table-cell', 'flow-root', 'inline-block'
  ]);

  const nodes = [];
  const frameElements = [];
  let seen = 0;
  let controlCount = 0;
  let truncated = false;

  /* --- small helpers ---------------------------------------------------- */

  function attr(el, name) {
    return el.hasAttribute(name) ? el.getAttribute(name) : null;
  }

  function tagOf(el) {
    return el.tagName.toLowerCase();
  }

  function collapse(text) {
    if (text === null || text === undefined) { return null; }
    const trimmed = String(text).replace(/\s+/g, ' ').trim();
    return trimmed;
  }

  function textOf(el) {
    if (!el) { return null; }
    const clone = el.cloneNode(true);
    clone.querySelectorAll('script, style').forEach((child) => child.remove());
    return collapse(clone.textContent);
  }

  function intAttr(el, name) {
    const value = attr(el, name);
    if (value === null) { return null; }
    const parsed = parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : null;
  }

  /* --- per-root bookkeeping --------------------------------------------- */

  /*
   * Ids are scoped to the tree they live in, so uniqueness is counted per root
   * rather than per page. An id that is unique in a shadow root and duplicated
   * in the document is addressable inside the root and not outside it, and the
   * selector this produces is only ever used inside the root.
   */
  function rootIndex(root) {
    const idCounts = new Map();
    const labelsFor = new Map();
    const byId = new Map();
    const all = root.querySelectorAll('*');
    for (const el of all) {
      const id = el.id;
      if (id) {
        idCounts.set(id, (idCounts.get(id) || 0) + 1);
        if (!byId.has(id)) { byId.set(id, el); }
      }
      if (tagOf(el) === 'label') {
        const target = attr(el, 'for');
        if (target !== null && !labelsFor.has(target)) { labelsFor.set(target, el); }
      }
    }
    return { idCounts, labelsFor, byId };
  }

  function nthOfType(el) {
    let index = 1;
    let sibling = el.previousElementSibling;
    while (sibling) {
      if (sibling.tagName === el.tagName) { index += 1; }
      sibling = sibling.previousElementSibling;
    }
    return index;
  }

  function stepFor(el, index) {
    const tag = tagOf(el);
    return {
      tag: tag,
      nth: nthOfType(el),
      id: el.id ? el.id : null,
      idUnique: el.id ? (index.idCounts.get(el.id) === 1) : false,
      formName: tag === 'form' ? attr(el, 'name') : null
    };
  }

  /*
   * The chain runs from the top of the root down to the element itself. For a
   * document that means it starts at <body>, because <html> is the anchor of
   * last resort rather than a step; for a shadow root it starts at the root's
   * own first element child.
   */
  function chainOf(el, root, index) {
    const steps = [];
    let cursor = el;
    while (cursor && cursor !== root) {
      if (cursor.nodeType !== 1) { break; }
      if (tagOf(cursor) === 'html') { break; }
      steps.push(stepFor(cursor, index));
      cursor = cursor.parentElement;
    }
    steps.reverse();
    return steps;
  }

  /* --- control detection ------------------------------------------------ */

  function isControl(el) {
    const tag = tagOf(el);
    if (tag === 'input') {
      const type = (attr(el, 'type') || 'text').toLowerCase();
      return !SKIPPED_INPUT_TYPES.has(type);
    }
    if (tag === 'select' || tag === 'textarea') { return true; }
    const editable = attr(el, 'contenteditable');
    if (editable !== null && editable.toLowerCase() !== 'false') { return true; }
    const role = attr(el, 'role');
    if (role !== null && CONTROL_ROLES.has(role.toLowerCase())) { return true; }
    return false;
  }

  function isFormAssociatedCustomElement(el) {
    const tag = tagOf(el);
    if (tag.indexOf('-') === -1) { return false; }
    let constructor = null;
    try { constructor = window.customElements.get(tag) || null; } catch (error) { constructor = null; }
    if (constructor === null) { return false; }
    if (constructor.formAssociated === true) { return true; }
    if (attr(el, 'name') !== null) { return true; }
    if (attr(el, 'placeholder') !== null) { return true; }
    if (attr(el, 'aria-label') !== null) { return true; }
    if (attr(el, 'role') !== null && CONTROL_ROLES.has(attr(el, 'role').toLowerCase())) {
      return true;
    }
    return el.tabIndex >= 0;
  }

  /* --- text context ----------------------------------------------------- */

  function ancestorsOf(el) {
    /*
     * Ancestors of an element, continuing through a shadow boundary onto the
     * host. Spec section 9.1 walks shadow content in place precisely because it
     * belongs to the surrounding form, so its context comes from there too: a
     * control inside a custom element has no form, no fieldset, and no heading
     * of its own, and the ones around the host are the true answer.
     */
    const chain = [];
    let cursor = el.parentNode;
    while (cursor) {
      if (cursor.nodeType === 1) {
        chain.push(cursor);
        cursor = cursor.parentNode;
      } else if (cursor.nodeType === 11 && cursor.host) {
        cursor = cursor.host;
      } else {
        cursor = cursor.parentNode;
      }
    }
    return chain;
  }

  function closestAcrossShadow(el, tagName) {
    for (const ancestor of ancestorsOf(el)) {
      if (tagOf(ancestor) === tagName) { return ancestor; }
    }
    return null;
  }

  function blockContainer(el) {
    let cursor = el.parentElement;
    while (cursor) {
      const display = window.getComputedStyle(cursor).display;
      if (BLOCK_DISPLAYS.has(display)) { return cursor; }
      cursor = cursor.parentElement;
    }
    return null;
  }

  function precedingSiblingText(node) {
    let sibling = node.previousSibling;
    while (sibling) {
      if (sibling.nodeType === 3) {
        const text = collapse(sibling.textContent);
        if (text) { return text; }
      } else if (sibling.nodeType === 1) {
        const tag = tagOf(sibling);
        /*
         * Labels are skipped on purpose. They are already collected as labels,
         * and counting one twice would weight the same words twice in the
         * feature space while looking like two independent pieces of evidence.
         */
        if (!SKIPPED_SUBTREES.has(tag) && tag !== 'label') {
          const text = textOf(sibling);
          if (text) { return text; }
        }
      }
      sibling = sibling.previousSibling;
    }
    return null;
  }

  function precedingText(el) {
    /*
     * The nearest visible text before the control **within the same
     * block-level container** (spec section 9.2). The container bound is what
     * keeps the signal honest: without it, a field whose own cell holds nothing
     * but a label would inherit the previous field's label as its context, and
     * every unlabelled field in a column would be described by the field above
     * it.
     */
    const container = blockContainer(el);
    let cursor = el;
    let steps = 0;
    while (cursor && cursor !== container && steps < 8) {
      const text = precedingSiblingText(cursor);
      if (text) { return text; }
      cursor = cursor.parentElement;
      steps += 1;
    }
    const root = el.getRootNode();
    if (root && root.nodeType === 11 && root.host) {
      /*
       * Shadow content is walked in place because it belongs to the surrounding
       * form (spec section 9.1). Its context comes from there too, so a control
       * with nothing before it inside its own root asks the host.
       */
      return precedingText(root.host);
    }
    return null;
  }

  function sectionHeading(el) {
    /*
     * The heading that introduces the block this control is in: rise through
     * the ancestors and take the last heading that appears before the branch
     * the control came down. The nearest one wins, so a field inside a section
     * gets that section's heading rather than the page title.
     */
    let child = el;
    for (const ancestor of ancestorsOf(el)) {
      let found = null;
      for (const sibling of ancestor.children) {
        if (sibling === child) { break; }
        if (/^h[1-6]$/.test(tagOf(sibling))) { found = sibling; }
      }
      if (found) { return textOf(found); }
      const tag = tagOf(ancestor);
      if (tag === 'body' || tag === 'html') { break; }
      child = ancestor;
    }
    return null;
  }

  function resolveIdList(el, attribute, index) {
    const value = attr(el, attribute);
    if (value === null) { return null; }
    const parts = value.split(/\s+/).filter((part) => part.length > 0);
    if (parts.length === 0) { return ''; }
    const texts = [];
    for (const part of parts) {
      const target = index.byId.get(part);
      if (target) {
        const text = textOf(target);
        if (text) { texts.push(text); }
      }
    }
    return texts.join(' ');
  }

  function formAccessibleName(form, index) {
    if (!form) { return null; }
    const aria = attr(form, 'aria-label');
    if (aria !== null) { return collapse(aria); }
    const labelled = resolveIdList(form, 'aria-labelledby', index);
    if (labelled !== null && labelled !== '') { return labelled; }
    const title = attr(form, 'title');
    if (title !== null) { return collapse(title); }
    return null;
  }

  function labelAncestorText(el) {
    const label = closestAcrossShadow(el, 'label');
    if (!label) { return null; }
    const clone = label.cloneNode(true);
    clone.querySelectorAll('input, select, textarea, script, style').forEach(
      (child) => child.remove()
    );
    return collapse(clone.textContent);
  }

  /* --- geometry --------------------------------------------------------- */

  function geometry(el) {
    let rect = null;
    try { rect = el.getBoundingClientRect(); } catch (error) { rect = null; }
    const style = window.getComputedStyle(el);
    const styleHidden = style.display === 'none'
      || style.visibility === 'hidden'
      || style.visibility === 'collapse'
      || parseFloat(style.opacity || '1') < 0.05;
    if (rect === null) {
      return { bbox: null, styleHidden: styleHidden, zeroSize: true, offscreen: false };
    }
    const left = rect.left + window.scrollX;
    const top = rect.top + window.scrollY;
    const zeroSize = rect.width <= 0 || rect.height <= 0;
    /*
     * Offscreen means off the top or the left of the document, which is what
     * `position:absolute; left:-9999px` produces. A control below the fold is
     * not offscreen: the comparison is against the document origin, never
     * against the viewport, so a long form is not a page full of honeypots.
     */
    const offscreen = (left + rect.width) <= 0 || (top + rect.height) <= 0;
    return {
      bbox: [left, top, rect.width, rect.height],
      styleHidden: styleHidden,
      zeroSize: zeroSize,
      offscreen: offscreen
    };
  }

  /* --- record building -------------------------------------------------- */

  function optionsOf(el) {
    if (tagOf(el) !== 'select') {
      return { labels: [], values: [], count: 0 };
    }
    const total = el.options.length;
    const limit = Math.min(total, MAX_OPTIONS);
    const labels = [];
    const values = [];
    for (let i = 0; i < limit; i += 1) {
      const option = el.options[i];
      labels.push(collapse(option.textContent) || '');
      values.push(option.value === null || option.value === undefined ? '' : option.value);
    }
    return { labels: labels, values: values, count: total };
  }

  function dataKeys(el) {
    const keys = [];
    for (const attribute of el.attributes) {
      const name = attribute.name.toLowerCase();
      if (name.indexOf('data-') === 0 && name.length > 5) {
        /*
         * The key without its prefix. Spec section 9.2 is emphatic that values
         * never leave the page; the prefix is dropped because it is the same on
         * every one of them and would otherwise put the token "data" into every
         * identifier stream that has a data attribute in it.
         */
        keys.push(name.slice(5));
      }
    }
    return keys;
  }

  function frameworkAttrs(el) {
    const pairs = [];
    for (const name of FRAMEWORK_ATTRS) {
      const value = attr(el, name);
      if (value !== null) { pairs.push([name, value]); }
    }
    return pairs;
  }

  function keyOf(el, counters) {
    if (el === null) { return null; }
    if (!counters.keys.has(el)) {
      counters.next += 1;
      counters.keys.set(el, 'e' + counters.next);
    }
    return counters.keys.get(el);
  }

  function controlRecord(el, context) {
    const tag = tagOf(el);
    const index = context.index;
    const counters = context.counters;
    const form = el.form !== undefined && el.form !== null
      ? el.form
      : closestAcrossShadow(el, 'form');
    const fieldset = closestAcrossShadow(el, 'fieldset');
    const parent = el.parentElement;

    const formKey = keyOf(form, counters);
    if (formKey !== null && !counters.formCounts.has(formKey)) {
      counters.formCounts.set(formKey, 0);
      counters.formNames.set(formKey, new Map());
    }
    const fieldsetKey = keyOf(fieldset, counters);
    if (fieldsetKey !== null && !counters.fieldsetCounts.has(fieldsetKey)) {
      counters.fieldsetCounts.set(fieldsetKey, 0);
    }

    let formIndex = null;
    if (formKey !== null) {
      formIndex = counters.formCounts.get(formKey);
      counters.formCounts.set(formKey, formIndex + 1);
    }
    let fieldsetIndex = null;
    if (fieldsetKey !== null) {
      fieldsetIndex = counters.fieldsetCounts.get(fieldsetKey);
      counters.fieldsetCounts.set(fieldsetKey, fieldsetIndex + 1);
    }

    const name = attr(el, 'name');
    if (formKey !== null && name !== null) {
      const names = counters.formNames.get(formKey);
      names.set(name, (names.get(name) || 0) + 1);
    }

    let siblingControls = 0;
    if (parent) {
      for (const child of parent.children) {
        if (child !== el && isControl(child)) { siblingControls += 1; }
      }
    }

    /*
     * A label's `for` attribute names one element: the one getElementById would
     * return, which is the first in tree order carrying that id. When an id is
     * duplicated, the second element carrying it is NOT labelled, and saying it
     * was would put somebody else's label on it.
     */
    const labelElement = el.id && index.byId.get(el.id) === el
      ? (index.labelsFor.get(el.id) || null)
      : null;
    const geo = geometry(el);
    const optionData = optionsOf(el);
    const inputType = tag === 'input' ? ((attr(el, 'type') || 'text').toLowerCase()) : null;

    return {
      kind: 'control',
      tag: tag,
      inputType: inputType,
      inputmode: attr(el, 'inputmode'),
      pattern: attr(el, 'pattern'),
      maxlength: intAttr(el, 'maxlength'),
      minlength: intAttr(el, 'minlength'),
      required: el.hasAttribute('required'),
      readonly: el.hasAttribute('readonly'),
      disabled: el.hasAttribute('disabled'),
      multiple: el.hasAttribute('multiple'),
      step: attr(el, 'step'),
      min: attr(el, 'min'),
      max: attr(el, 'max'),
      autocompleteRaw: attr(el, 'autocomplete'),
      name: name,
      elementId: el.id ? el.id : null,
      cssClasses: Array.from(el.classList),
      dataKeys: dataKeys(el),
      frameworkAttrs: frameworkAttrs(el),
      labelFor: labelElement ? textOf(labelElement) : null,
      labelAncestor: labelAncestorText(el),
      ariaLabel: attr(el, 'aria-label') === null ? null : collapse(attr(el, 'aria-label')),
      ariaLabelledbyText: resolveIdList(el, 'aria-labelledby', index),
      ariaDescribedbyText: resolveIdList(el, 'aria-describedby', index),
      title: attr(el, 'title') === null ? null : collapse(attr(el, 'title')),
      placeholder: attr(el, 'placeholder') === null ? null : collapse(attr(el, 'placeholder')),
      precedingText: precedingText(el),
      legend: fieldset ? textOf(fieldset.querySelector('legend')) : null,
      sectionHeading: sectionHeading(el),
      formAccessibleName: formAccessibleName(form, index),
      optionLabels: optionData.labels,
      optionValues: optionData.values,
      optionCount: optionData.count,
      formKey: formKey,
      formIndex: formIndex,
      fieldsetKey: fieldsetKey,
      fieldsetIndex: fieldsetIndex,
      siblingControlCount: siblingControls,
      parentKey: keyOf(parent, counters) || '',
      chain: chainOf(el, context.root, index),
      shadowHostChains: context.hostChains.slice(),
      bbox: geo.bbox,
      styleHidden: geo.styleHidden,
      zeroSize: geo.zeroSize,
      offscreen: geo.offscreen,
      nameUniqueInForm: false
    };
  }

  /* --- the walk --------------------------------------------------------- */

  function walk(node, context) {
    for (const el of node.children) {
      if (truncated) { return; }
      const tag = tagOf(el);
      if (SKIPPED_SUBTREES.has(tag)) { continue; }

      if (isControl(el)) {
        seen += 1;
        if (controlCount >= MAX_CONTROLS) {
          truncated = true;
          return;
        }
        controlCount += 1;
        nodes.push(controlRecord(el, context));
        continue;
      }

      if (tag === 'iframe' || tag === 'frame') {
        let accessible = false;
        try {
          accessible = !!(el.contentDocument && el.contentDocument.documentElement);
        } catch (error) {
          accessible = false;
        }
        nodes.push({
          kind: 'frame',
          tag: tag,
          accessible: accessible,
          src: attr(el, 'src'),
          name: attr(el, 'name'),
          frameIndex: frameElements.length,
          chain: chainOf(el, context.root, context.index),
          shadowHostChains: context.hostChains.slice()
        });
        frameElements.push(el);
        continue;
      }

      if (tag === 'canvas') {
        const rect = el.getBoundingClientRect();
        const width = rect.width || el.width || 0;
        const height = rect.height || el.height || 0;
        if (width * height >= MIN_CANVAS_AREA) {
          nodes.push({
            kind: 'canvas',
            width: width,
            height: height,
            chain: chainOf(el, context.root, context.index),
            shadowHostChains: context.hostChains.slice()
          });
        }
        continue;
      }

      const shadow = el.shadowRoot;
      if (shadow) {
        /* Rule 1: in place, before the host's siblings. */
        const hostChain = chainOf(el, context.root, context.index);
        const shadowIndex = rootIndex(shadow);
        walk(shadow, {
          root: shadow,
          index: shadowIndex,
          counters: context.counters,
          hostChains: context.hostChains.concat([hostChain])
        });
        walk(el, context);
        continue;
      }

      if (isFormAssociatedCustomElement(el)
          && el.querySelectorAll('input, select, textarea').length === 0) {
        /* Rule 3: name the blind spot rather than pretend the field is absent. */
        nodes.push({
          kind: 'closedShadow',
          tag: tag,
          chain: chainOf(el, context.root, context.index),
          shadowHostChains: context.hostChains.slice()
        });
        continue;
      }

      walk(el, context);
    }
  }

  const documentIndex = rootIndex(document);
  const counters = {
    keys: new WeakMap(),
    next: 0,
    formCounts: new Map(),
    formNames: new Map(),
    fieldsetCounts: new Map()
  };
  walk(document.documentElement, {
    root: document,
    index: documentIndex,
    counters: counters,
    hostChains: []
  });

  /*
   * Name uniqueness inside a form can only be known once the whole root has
   * been walked, so it is filled in here rather than guessed at during the
   * walk. It matters because every member of a radio group shares one name, and
   * the second selector preference would hand all of them the same selector.
   */
  for (const record of nodes) {
    if (record.kind !== 'control' || record.formKey === null || record.name === null) { continue; }
    const names = counters.formNames.get(record.formKey);
    record.nameUniqueInForm = names.get(record.name) === 1;
  }

  return { nodes: nodes, frameElements: frameElements, seen: seen, truncated: truncated };
}
