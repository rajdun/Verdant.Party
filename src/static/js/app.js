/* Drobne zachowania UI: szuflada nawigacji, paleta ⌘K, przewijane tabele. */
(function () {
    'use strict';

    var body = document.body;

    /* ── Szuflada nawigacji (mobile) ──────────────────────────────────── */

    var toggle = document.querySelector('.nav-toggle');
    var scrim = document.querySelector('.scrim');

    function setNav(open) {
        body.classList.toggle('nav-open', open);
        if (scrim) { scrim.hidden = !open; }
        if (toggle) { toggle.setAttribute('aria-expanded', String(open)); }
    }

    if (toggle) {
        toggle.addEventListener('click', function () {
            setNav(!body.classList.contains('nav-open'));
        });
    }

    document.querySelectorAll('[data-close-nav]').forEach(function (el) {
        el.addEventListener('click', function () { setNav(false); });
    });

    /* Klik w link zamyka szufladę — nawigacja i tak przeładuje stronę,
       ale bez tego widać przeskok przy powrocie z cache. */
    document.querySelectorAll('.sidebar-nav a').forEach(function (link) {
        link.addEventListener('click', function () { setNav(false); });
    });

    /* ── Paleta szybkiej nawigacji ────────────────────────────────────── */

    var palette = document.getElementById('palette');
    var paletteList = document.getElementById('palette-list');
    var paletteQuery = document.getElementById('palette-query');
    var items = [];
    var cursor = 0;

    if (palette && paletteList && paletteQuery) {
        var group = '';
        document.querySelectorAll('.sidebar-nav > *').forEach(function (el) {
            if (el.classList.contains('nav-group-label')) {
                group = el.textContent.trim();
                return;
            }
            if (el.tagName !== 'A') { return; }
            var icon = el.querySelector('.material-icons');
            /* Ligatura ikony siedzi w textContent — kopiuję link bez niej, żeby została sama nazwa */
            var bare = el.cloneNode(true);
            var bareIcon = bare.querySelector('.material-icons');
            if (bareIcon) { bareIcon.remove(); }
            items.push({
                label: bare.textContent.trim(),
                group: group,
                icon: icon ? icon.textContent.trim() : 'chevron_right',
                href: el.getAttribute('href')
            });
        });

        var render = function (query) {
            var q = query.trim().toLowerCase();
            var matches = items.filter(function (item) {
                return !q || (item.label + ' ' + item.group).toLowerCase().indexOf(q) !== -1;
            });
            cursor = 0;
            paletteList.innerHTML = '';
            if (!matches.length) {
                var empty = document.createElement('li');
                empty.className = 'palette-empty';
                empty.textContent = 'Nic nie pasuje.';
                paletteList.appendChild(empty);
                return;
            }
            matches.forEach(function (item, index) {
                var li = document.createElement('li');
                var a = document.createElement('a');
                a.href = item.href;
                a.className = 'palette-item' + (index === 0 ? ' is-active' : '');
                a.innerHTML = '<span class="material-icons" aria-hidden="true"></span>' +
                    '<span class="palette-label"></span><span class="palette-group"></span>';
                a.querySelector('.material-icons').textContent = item.icon;
                a.querySelector('.palette-label').textContent = item.label;
                a.querySelector('.palette-group').textContent = item.group;
                a.addEventListener('mouseenter', function () {
                    cursor = index;
                    highlight();
                });
                li.appendChild(a);
                paletteList.appendChild(li);
            });
        };

        var highlight = function () {
            var links = paletteList.querySelectorAll('.palette-item');
            links.forEach(function (el, index) {
                el.classList.toggle('is-active', index === cursor);
            });
            var active = links[cursor];
            if (active) { active.scrollIntoView({ block: 'nearest' }); }
        };

        var openPalette = function () {
            render('');
            paletteQuery.value = '';
            palette.hidden = false;
            body.classList.add('palette-open-state');
            requestAnimationFrame(function () { paletteQuery.focus(); });
        };

        var closePalette = function () {
            palette.hidden = true;
            body.classList.remove('palette-open-state');
        };

        document.querySelectorAll('.palette-open').forEach(function (el) {
            el.addEventListener('click', function () {
                setNav(false);
                openPalette();
            });
        });

        document.querySelectorAll('[data-close-palette]').forEach(function (el) {
            el.addEventListener('click', closePalette);
        });

        paletteQuery.addEventListener('input', function () { render(paletteQuery.value); });

        paletteQuery.addEventListener('keydown', function (event) {
            var links = paletteList.querySelectorAll('.palette-item');
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                cursor = Math.min(cursor + 1, links.length - 1);
                highlight();
            } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                cursor = Math.max(cursor - 1, 0);
                highlight();
            } else if (event.key === 'Enter') {
                if (links[cursor]) {
                    event.preventDefault();
                    links[cursor].click();
                }
            }
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'k' && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                if (palette.hidden) { openPalette(); } else { closePalette(); }
            } else if (event.key === 'Escape') {
                if (!palette.hidden) { closePalette(); }
                setNav(false);
            }
        });
    }

    /* ── Karta filtrów: zwijana, domyślnie schowana na wąskim ekranie ─── */

    document.querySelectorAll('.card').forEach(function (card) {
        var grid = card.querySelector('.filters-grid');
        var heading = card.querySelector('h3');
        if (!grid || !heading || !card.querySelector('form')) { return; }

        var toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'card-toggle';
        toggle.innerHTML = '<span>' + heading.textContent.trim() + '</span>' +
            '<span class="material-icons" aria-hidden="true">expand_more</span>';
        heading.replaceWith(toggle);
        card.classList.add('is-collapsible');

        /* Z aktywnymi parametrami filtr zostaje otwarty — inaczej nie widać, czemu lista jest krótka. */
        var hasQuery = window.location.search.replace(/^\?/, '').length > 0;
        var collapsed = window.matchMedia('(max-width: 900px)').matches && !hasQuery;
        var apply = function () {
            card.classList.toggle('is-collapsed', collapsed);
            toggle.setAttribute('aria-expanded', String(!collapsed));
        };
        apply();

        toggle.addEventListener('click', function () {
            collapsed = !collapsed;
            apply();
        });
    });

    /* ── Tabele: poziome przewijanie + cień krawędzi zamiast łamania ──── */

    document.querySelectorAll('.data-table').forEach(function (table) {
        if (table.closest('.table-wrap') || table.closest('.detail-row')) { return; }
        var wrap = document.createElement('div');
        wrap.className = 'table-wrap';
        table.parentNode.insertBefore(wrap, table);
        wrap.appendChild(table);

        var sync = function () {
            var max = wrap.scrollWidth - wrap.clientWidth;
            wrap.classList.toggle('has-left', wrap.scrollLeft > 2);
            wrap.classList.toggle('has-right', wrap.scrollLeft < max - 2);
        };
        wrap.addEventListener('scroll', sync, { passive: true });
        window.addEventListener('resize', sync);
        sync();
    });
}());
