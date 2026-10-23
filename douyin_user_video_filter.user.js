// ==UserScript==
// @name         Douyin User Video Filter
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  Extract Douyin user videos and filter them by likes and duration
// @author       You
// @match        https://www.douyin.com/user/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function() {
    'use strict';

    /* ------------------------------------------------------------------ *
     *  CONFIGURATION / SELECTORS                                         *
     * ------------------------------------------------------------------ */

    const SEL = {
        container : 'li.AhHE71Bq.F4b7sztk.zvGw4rBu',   // video card <li>
        link      : 'a[href*="/video/"]',                // video anchor
        title     : '.EB3BkdQ8, .frUrWD64.RpuhoKEt',    // video title / description
        likes     : '.HycZGr_s .BP1CQkLg',              // like-count span
        cover     : '.iWV3dpj1.wzoPLIem img'            // thumbnail (used as fallback)
    };

    // Douyin renders like counts like "1405", "1.2万", "3.5k"
    function parseLikes(text) {
        if (!text) return 0;
        const t = text.trim().replace(/,/g, '');
        if (t === '') return 0;
        if (t.endsWith('万')) return Math.floor(parseFloat(t) * 10000) || 0;
        if (t.endsWith('k') || t.endsWith('K')) return Math.floor(parseFloat(t) * 1000) || 0;
        return parseInt(t, 10) || 0;
    }

    // Duration appears on Douyin covers as "M:SS" (e.g. "1:23", "0:45")
    function parseDuration(text) {
        if (!text) return null;
        const m = text.trim().match(/^(\d{1,2}):(\d{2})$/);
        if (!m) return null;
        return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
    }

    function formatDuration(seconds) {
        if (seconds == null) return 'N/A';
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return m + ':' + String(s).padStart(2, '0');
    }

    /* ------------------------------------------------------------------ *
     *  STATE                                                             *
     * ------------------------------------------------------------------ */

    let videos = [];   // [{element, url, title, likes, duration, durationText}]
    let ui = null;

    /* ------------------------------------------------------------------ *
     *  AUTO-SCROLL TO END                                                *
     * ------------------------------------------------------------------ */

    let isScrolling = false;
    let scrollAttempts = 0;
    const MAX_SCROLL_ATTEMPTS = 100;
    const SCROLL_DELAY_MS = 2500;
    let endOfPageFound = false;

    function checkEndOfPage() {
        const nodes = document.querySelectorAll('font[dir="auto"][style="vertical-align: inherit"]');
        for (const node of nodes) {
            if (node.textContent && node.textContent.includes("That's all for now")) {
                return true;
            }
        }
        return false;
    }

    async function autoScrollToEnd() {
        if (isScrolling || endOfPageFound) return;
        isScrolling = true;
        scrollAttempts = 0;

        const statusEl = ui && ui.panel ? ui.panel.querySelector('#dy-scroll-status') : null;
        const btn = ui && ui.panel ? ui.panel.querySelector('#dy-scroll-btn') : null;

        while (scrollAttempts < MAX_SCROLL_ATTEMPTS && !endOfPageFound) {
            if (checkEndOfPage()) {
                endOfPageFound = true;
                break;
            }
            window.scrollBy(0, window.innerHeight);
            scrollAttempts++;
            if (statusEl) statusEl.textContent = 'Scrolling... ' + scrollAttempts + '/' + MAX_SCROLL_ATTEMPTS;
            await new Promise(resolve => setTimeout(resolve, SCROLL_DELAY_MS));
        }

        isScrolling = false;
        if (btn) btn.textContent = endOfPageFound ? 'End Reached' : 'Scroll Again';
        if (statusEl) statusEl.textContent = endOfPageFound
            ? 'End of page detected ("That\'s all for now.")'
            : 'Scroll limit reached without finding end.';

        if (endOfPageFound) {
            scanVideos();
            applyFilters();
            showQualifiedUrls();
        }
    }

    /* ------------------------------------------------------------------ *
     *  SCANNING                                                          *
     * ------------------------------------------------------------------ */

    function findDurationInCard(li) {
        // 1) Try common duration classes first
        const durationEls = li.querySelectorAll(
            '[class*="Duration"], [class*="duration"], [class*="VideoTime"], [class*="video-time"], [class*="time"]'
        );
        for (const el of durationEls) {
            const d = parseDuration(el.textContent);
            if (d != null) return { d, text: el.textContent.trim() };
        }
        // 2) Fallback: scan all text nodes inside the card for "M:SS"
        const walker = document.createTreeWalker(li, NodeFilter.SHOW_TEXT, null, false);
        let node;
        while (node = walker.nextNode()) {
            const d = parseDuration(node.textContent);
            if (d != null) {
                return { d, text: node.textContent.trim() };
            }
        }
        return { d: null, text: 'N/A' };
    }

    function scanVideos() {
        const list = [];
        document.querySelectorAll(SEL.container).forEach(li => {
            const a = li.querySelector(SEL.link);
            if (!a) return;

            const href = a.getAttribute('href') || '';
            const url = href.startsWith('http') ? href : 'https://www.douyin.com' + href;

            const titleEl = li.querySelector(SEL.title);
            const title = titleEl ? titleEl.textContent.trim() : '';

            const likesEl = li.querySelector(SEL.likes);
            const likes = likesEl ? parseLikes(likesEl.textContent) : 0;

            const { d: duration, text: durationText } = findDurationInCard(li);

            list.push({
                element : li,
                url,
                title,
                likes,
                duration,
                durationText
            });
        });
        videos = list;
        updateStats();
        applyFilters();
    }


    /* ------------------------------------------------------------------ *
     *  FILTERING                                                         *
     * ------------------------------------------------------------------ */

    function getFilterValues() {
        if (!ui) return null;
        return {
            minLikes : parseInt(ui.minLikes.value, 10) || 0,
            maxLikes : ui.maxLikes.value === '' ? Infinity : parseInt(ui.maxLikes.value, 10),
            minDur   : ui.minDur.value === '' ? 0 : parseInt(ui.minDur.value, 10),
            maxDur   : ui.maxDur.value === '' ? Infinity : parseInt(ui.maxDur.value, 10)
        };
    }

    function applyFilters() {
        const f = getFilterValues();
        if (!f) return;

        let shown = 0;
        videos.forEach(v => {
            const ok =
                v.likes >= f.minLikes &&
                v.likes <= f.maxLikes &&
                (v.duration == null || (v.duration >= f.minDur && v.duration <= f.maxDur));
            v.element.style.display = ok ? '' : 'none';
            if (ok) shown++;
        });
        ui.count.textContent = shown + ' / ' + videos.length;
    }

    function showQualifiedUrls() {
        const f = getFilterValues();
        if (!f) return;

        const qualified = videos.filter(v =>
            v.likes >= f.minLikes &&
            v.likes <= f.maxLikes &&
            (v.duration == null || (v.duration >= f.minDur && v.duration <= f.maxDur))
        );

        const countEl = ui.panel.querySelector('#dy-qualified-count');
        const listEl = ui.panel.querySelector('#dy-qualified-list');

        if (countEl) countEl.textContent = 'Qualified: ' + qualified.length;
        if (listEl) {
            listEl.innerHTML = '';
            if (qualified.length === 0) {
                listEl.textContent = 'No videos match the current filters.';
            } else {
                qualified.forEach(v => {
                    const div = document.createElement('div');
                    div.style.padding = '4px 0';
                    div.style.borderBottom = '1px solid #f0f0f0';
                    div.style.fontSize = '11px';
                    div.style.lineHeight = '1.3';
                    div.innerHTML =
                        '<a href="' + v.url + '" target="_blank" style="color:#fe2c55; text-decoration:none; font-weight:bold;">' + v.url + '</a>' +
                        '<div style="font-size:10px; color:#666; margin-top:2px;">' +
                        'likes: ' + v.likes + ' | duration: ' + v.durationText + ' | ' + v.title +
                        '</div>';
                    listEl.appendChild(div);
                });
            }
        }

        console.log('[Douyin Filter] Qualified URLs:', qualified.map(v => v.url));
    }

    /* ------------------------------------------------------------------ *
     *  UI                                                                *
     * ------------------------------------------------------------------ */

    const CSS = `
#dy-filter-panel {
    position: fixed;
    top: 10px;
    left: 10px;
    z-index: 2147483647;
    background: #fff;
    border: 1px solid #ccc;
    border-radius: 8px;
    padding: 12px 16px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
    line-height: 1.4;
    max-width: 260px;
    user-select: none;
}
#dy-filter-panel h2 {
    margin: 0 0 10px 0;
    font-size: 15px;
    color: #111;
}
#dy-filter-panel .row {
    display: flex;
    gap: 8px;
    margin-bottom: 8px;
    align-items: center;
}
#dy-filter-panel label {
    font-size: 12px;
    color: #333;
    white-space: nowrap;
}
#dy-filter-panel input {
    flex: 1;
    padding: 4px 6px;
    font-size: 12px;
    border: 1px solid #bbb;
    border-radius: 4px;
    box-sizing: border-box;
}
#dy-filter-panel button {
    margin-top: 8px;
    padding: 6px 14px;
    font-size: 13px;
    background: #fe2c55;
    color: #fff;
    border: none;
    border-radius: 4px;
    cursor: pointer;
}
#dy-filter-panel button:hover { background: #e71e46; }
#dy-filter-panel .hint {
    font-size: 11px;
    color: #666;
    margin-top: 6px;
}
#dy-filter-panel .count {
    margin-top: 6px;
    font-weight: bold;
    color: #fe2c55;
}
#dy-filter-panel .close {
    float: right;
    cursor: pointer;
    font-weight: bold;
    color: #999;
}
#dy-filter-panel .close:hover { color: #333; }
`;

    function createUI() {
        const style = document.createElement('style');
        style.textContent = CSS;
        document.documentElement.appendChild(style);

        const panel = document.createElement('div');
        panel.id = 'dy-filter-panel';
        panel.innerHTML = `
            <span class="close" title="Close">×</span>
            <h2>Douyin Video Filter</h2>
            <div class="row">
                <label>Likes ≥</label>
                <input id="dy-min-likes" type="number" min="0" placeholder="0">
            </div>
            <div class="row">
                <label>Likes ≤</label>
                <input id="dy-max-likes" type="number" min="0" placeholder="∞">
            </div>
            <div class="row">
                <label>Duration ≥ (s)</label>
                <input id="dy-min-dur" type="number" min="0" placeholder="0">
            </div>
            <div class="row">
                <label>Duration ≤ (s)</label>
                <input id="dy-max-dur" type="number" min="0" placeholder="∞">
            </div>
            <button id="dy-apply">Apply Filters</button>
            <div class="row" style="margin-top:10px;">
                <button id="dy-scroll-btn" style="background:#2e86de; width:100%;">Scroll to End & Filter</button>
            </div>
            <div id="dy-scroll-status" style="font-size:11px; color:#666; margin:4px 0;"></div>
            <div class="count" id="dy-qualified-count" style="color:#2e86de;">Qualified: 0</div>
            <div id="dy-qualified-list" style="max-height:160px; overflow-y:auto; font-size:11px; border-top:1px solid #eee; padding-top:6px; margin-top:6px;"></div>
            <div class="hint">Leave a field blank for no limit.</div>
            <div class="count" id="dy-count">0 / 0</div>
        `;
        document.body.appendChild(panel);

        ui = {
            panel,
            minLikes : panel.querySelector('#dy-min-likes'),
            maxLikes : panel.querySelector('#dy-max-likes'),
            minDur   : panel.querySelector('#dy-min-dur'),
            maxDur   : panel.querySelector('#dy-max-dur'),
            count    : panel.querySelector('#dy-count')
        };

        panel.querySelector('.close').addEventListener('click', () => panel.style.display = 'none');
        panel.querySelector('#dy-apply').addEventListener('click', applyFilters);
        panel.querySelector('#dy-scroll-btn').addEventListener('click', autoScrollToEnd);

        // Live-update while typing
        [ui.minLikes, ui.maxLikes, ui.minDur, ui.maxDur].forEach(inp => {
            inp.addEventListener('input', applyFilters);
        });
    }

    function updateStats() {
        if (ui) ui.count.textContent = videos.length + ' videos found';
    }

    /* ------------------------------------------------------------------ *
     *  DYNAMIC CONTENT (infinite scroll / navigation)                    *
     * ------------------------------------------------------------------ */

    const observer = new MutationObserver(scanVideos);
    function startObserving() {
        observer.observe(document.body, { childList: true, subtree: true });
    }

    // Re-scan periodically and on scroll (Douyin lazy-loads more cards)
    let ticking = false;
    window.addEventListener('scroll', () => {
        if (!ticking) {
            ticking = true;
            requestAnimationFrame(() => {
                scanVideos();
                ticking = false;
            });
        }
    }, { passive: true });

    /* ------------------------------------------------------------------ *
     *  INIT                                                              *
     * ------------------------------------------------------------------ */

    function init() {
        createUI();
        // Auto-scroll to end of page, then compute the qualified list & URLs
        setTimeout(() => {
            autoScrollToEnd();
            startObserving();
        }, 2000);
        // Re-scan every few seconds to catch newly loaded cards while scrolling
        setInterval(scanVideos, 5000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();

