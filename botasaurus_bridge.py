"""
Botasaurus Bridge - Selenium uyumlu wrapper
Botasaurus Driver'ı Selenium API'sine benzer bir arayüzle sarar.
Cloudflare bypass otomatik olarak yapılır.
"""
import time
import json
import threading
from botasaurus_driver import Driver


# Selenium By uyumluluğu için sabitler
class By:
    ID = "id"
    CSS_SELECTOR = "css selector"
    XPATH = "xpath"
    TAG_NAME = "tag name"
    CLASS_NAME = "class name"
    NAME = "name"
    LINK_TEXT = "link text"
    PARTIAL_LINK_TEXT = "partial link text"


class BotElement:
    """Botasaurus element'ini Selenium element API'sine uyumlu wrapper"""

    def __init__(self, bot_element, bridge):
        self._el = bot_element
        self._bridge = bridge

    def click(self):
        self._el.click()

    @property
    def text(self):
        return self._el.text

    @property
    def tag_name(self):
        try:
            return self._el.apply("return element.tagName.toLowerCase()")
        except Exception:
            return ""

    def get_attribute(self, name):
        _dom_properties = ('innerHTML', 'outerHTML', 'textContent', 'innerText')
        try:
            result = self._el.get_attribute(name)
            # DOM property'leri için boş string güvenilmez - fallback'e düş
            if result is not None and (result != '' or name not in _dom_properties):
                return result
        except Exception:
            pass
        # Fallback: JS ile al - innerHTML/outerHTML gibi property'ler için element[name] kullan
        try:
            # Önce DOM property olarak dene (innerHTML, outerHTML, textContent vb.)
            result = self._el.apply(f"return element['{name}']")
            if result is not None:
                return result
        except Exception:
            pass
        try:
            # Sonra HTML attribute olarak dene
            return self._el.apply(f"return element.getAttribute('{name}')")
        except Exception:
            return None

    @property
    def is_selected(self):
        try:
            return self._el.apply("return element.checked || element.selected || false")
        except Exception:
            return False

    @property
    def is_displayed(self):
        try:
            return self._el.apply("return element.offsetParent !== null")
        except Exception:
            return False

    def send_keys(self, text):
        """Input alanına metin yaz"""
        try:
            self._el.type(text)
        except Exception:
            # Fallback: JS ile - apply() element'i 'element' olarak geçirir
            escaped = str(text).replace('\\', '\\\\').replace("'", "\\'")
            self._el.apply(
                f"element.value = '{escaped}'; "
                "element.dispatchEvent(new Event('input', {bubbles: true})); "
                "element.dispatchEvent(new Event('change', {bubbles: true}));"
            )

    def clear(self):
        """Input alanını temizle"""
        try:
            self._el.apply(
                "element.value = ''; "
                "element.dispatchEvent(new Event('input', {bubbles: true}));"
            )
        except Exception:
            pass

    def find_element(self, by, value):
        """Alt element bul"""
        css = _by_to_css(by, value)
        if by == By.XPATH:
            # XPath: apply() ile parent context'te ara
            escaped_val = value.replace('\\', '\\\\').replace("'", "\\'")
            result = self._el.apply(f"""
                var xpath = '{escaped_val}';
                var result = document.evaluate(xpath, element, null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                return result.singleNodeValue;
            """)
            if result is None:
                raise NoSuchElementException(f"Element not found: {by}={value}")
            return BotElement(result, self._bridge)
        else:
            try:
                child = self._el.select(css)
                return BotElement(child, self._bridge)
            except Exception:
                raise NoSuchElementException(f"Element not found: {by}={value}")

    def find_elements(self, by, value):
        """Alt elementleri bul"""
        css = _by_to_css(by, value)
        if by == By.XPATH:
            escaped_val = value.replace('\\', '\\\\').replace("'", "\\'")
            results = self._el.apply(f"""
                var xpath = '{escaped_val}';
                var result = document.evaluate(xpath, element, null,
                    XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
                var nodes = [];
                for (var i = 0; i < result.snapshotLength; i++) {{
                    nodes.push(result.snapshotItem(i));
                }}
                return nodes;
            """)
            return [BotElement(r, self._bridge) for r in (results or [])]
        else:
            try:
                children = self._el.select_all(css)
                return [BotElement(c, self._bridge) for c in children]
            except Exception:
                return []


class NoSuchElementException(Exception):
    pass


class TimeoutException(Exception):
    pass


def _by_to_css(by, value):
    """Selenium By + value -> CSS selector dönüşümü"""
    if by == By.ID:
        return f"#{value}"
    elif by == By.CSS_SELECTOR:
        return value
    elif by == By.TAG_NAME:
        return value
    elif by == By.CLASS_NAME:
        # Birden fazla class olabilir (space separated)
        classes = value.strip().split()
        return "." + ".".join(classes)
    elif by == By.NAME:
        return f'[name="{value}"]'
    elif by == By.LINK_TEXT:
        # CSS ile tam metin eşlemesi yapılamaz, JS fallback gerekir
        return f'a'  # Tüm linkleri al, sonra filtrele
    elif by == By.PARTIAL_LINK_TEXT:
        return f'a'
    elif by == By.XPATH:
        return value  # XPath ayrı işlenir
    else:
        return value


class BotasaurusBridge:
    """Botasaurus Driver'ı Selenium-uyumlu API ile sarar"""

    def __init__(self, headless=False, lang="en", profile=None):
        """
        Args:
            headless: Headless mod
            lang: Tarayıcı dili (en, tr, vs.)
            profile: Chrome profil adı (cookie saklamak için)
        """
        driver_kwargs = {
            'headless': headless,
            'lang': lang,
        }
        if profile:
            driver_kwargs['profile'] = profile

        self.bot_driver = Driver(**driver_kwargs)
        self.bot_driver.enable_human_mode()
        self._maximize_thread = None

    def _navigate_with_timeout(self, url, bypass_cloudflare=True, timeout=30):
        """
        Timeout korumalı navigasyon. google_get çağrısı timeout süresi içinde
        tamamlanmazsa False döner ve bloke olmaz.
        
        Returns:
            bool: True=sayfa yüklendi, False=timeout oldu
        """
        import threading
        result = {'done': False, 'error': None}
        
        def _nav():
            try:
                self.bot_driver.google_get(url, bypass_cloudflare=bypass_cloudflare)
                result['done'] = True
            except Exception as e:
                result['error'] = e
        
        t = threading.Thread(target=_nav, daemon=True)
        t.start()
        t.join(timeout=timeout)
        
        if not result['done']:
            # Timeout oldu - thread hâlâ çalışıyor olabilir ama daemon olduğu için sorun değil
            if result['error']:
                raise result['error']
            return False
        
        if result['error']:
            raise result['error']
        return True

    def google_get(self, url, bypass_cloudflare=True, timeout=90):
        """Cloudflare bypass ile sayfa aç (timeout korumalı)"""
        import threading
        result = {'done': False, 'error': None}

        def _nav():
            try:
                self.bot_driver.google_get(url, bypass_cloudflare=bypass_cloudflare)
                result['done'] = True
            except Exception as e:
                result['error'] = e

        t = threading.Thread(target=_nav, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if not result['done']:
            if result['error']:
                raise result['error']
            raise TimeoutError(f"google_get {timeout}s timeout: {url}")

        if result['error']:
            raise result['error']

    def get(self, url, timeout=30):
        """Sayfa aç - Cloudflare bypass otomatik, timeout korumalı"""
        return self._navigate_with_timeout(url, bypass_cloudflare=True, timeout=timeout)

    def get_without_bypass(self, url, timeout=30):
        """Bypass olmadan sayfa aç - cookie'ler zaten set edilmişse kullan"""
        return self._navigate_with_timeout(url, bypass_cloudflare=False, timeout=timeout)

    def get_smart(self, url, wait_after=3, timeout=30):
        """
        Akıllı navigasyon: önce bypass olmadan dener, Cloudflare challenge
        tespit ederse bypass ile tekrar dener. Timeout korumalı.
        
        Returns:
            bool: True=sayfa başarıyla yüklendi, False=Cloudflare challenge'da kaldı veya timeout
        """
        import time as _time
        
        # Önce bypass olmadan dene (timeout ile)
        loaded = self._navigate_with_timeout(url, bypass_cloudflare=False, timeout=timeout)
        if not loaded:
            # Timeout oldu - bypass ile dene
            loaded = self._navigate_with_timeout(url, bypass_cloudflare=True, timeout=timeout)
            if not loaded:
                return False
            _time.sleep(wait_after)
            # Bypass sonrası kontrol
            try:
                page_title = self.title.lower()
                page_html_lower = self.page_source[:5000].lower()
                still_cf = (
                    'just a moment' in page_title
                    or 'attention required' in page_title
                    or 'checking your browser' in page_html_lower
                    or ('cloudflare' in page_html_lower and 'challenge' in page_html_lower)
                )
                return not still_cf
            except Exception:
                return False
        
        _time.sleep(wait_after)
        
        # Cloudflare challenge kontrolü
        try:
            page_title = self.title.lower()
            page_html_lower = self.page_source[:5000].lower()
            is_cloudflare = (
                'just a moment' in page_title
                or 'attention required' in page_title
                or 'checking your browser' in page_html_lower
                or ('cloudflare' in page_html_lower and 'challenge' in page_html_lower)
            )
        except Exception:
            is_cloudflare = False
        
        if is_cloudflare:
            # Challenge var, bypass ile tekrar dene (timeout ile)
            loaded = self._navigate_with_timeout(url, bypass_cloudflare=True, timeout=timeout)
            if not loaded:
                return False
            _time.sleep(wait_after)
            
            # Tekrar kontrol
            try:
                page_title = self.title.lower()
                page_html_lower = self.page_source[:5000].lower()
                still_cloudflare = (
                    'just a moment' in page_title
                    or 'attention required' in page_title
                    or 'checking your browser' in page_html_lower
                    or ('cloudflare' in page_html_lower and 'challenge' in page_html_lower)
                )
                return not still_cloudflare
            except Exception:
                return False
        
        return True

    @property
    def page_source(self):
        """Selenium uyumlu page_source property"""
        return self.bot_driver.page_html

    @property
    def current_url(self):
        """Mevcut URL"""
        try:
            return self.bot_driver.run_js("return window.location.href")
        except Exception:
            return ""

    @property
    def title(self):
        """Sayfa başlığı"""
        try:
            return self.bot_driver.run_js("return document.title")
        except Exception:
            return ""

    @property
    def current_window_handle(self):
        """Selenium uyumluluğu için - tek pencere varsayımı"""
        return "main"

    @property
    def switch_to(self):
        """Selenium switch_to uyumluluğu"""
        return self

    def window(self, handle):
        """switch_to.window() uyumluluğu - tek pencere, no-op"""
        pass

    def find_element(self, by, value):
        """Selenium uyumlu find_element"""
        if by == By.XPATH:
            # XPath içinde tek tırnak olabilir, JSON.parse ile çakışmasın diye
            # değeri doğrudan JS'e embed ediyoruz
            escaped = value.replace('\\', '\\\\').replace('`', '\\`').replace('${', '\\${')
            result = self.bot_driver.run_js(f"""
                var xpath = `{escaped}`;
                var result = document.evaluate(xpath, document, null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                return result.singleNodeValue;
            """)
            if result is None:
                raise NoSuchElementException(f"Element not found: XPATH={value}")
            return BotElement(result, self)
        elif by == By.LINK_TEXT:
            escaped = value.replace('\\', '\\\\').replace('`', '\\`').replace('${', '\\${')
            result = self.bot_driver.run_js(f"""
                var links = document.querySelectorAll('a');
                var text = `{escaped}`;
                for (var i = 0; i < links.length; i++) {{
                    if (links[i].textContent.trim() === text) return links[i];
                }}
                return null;
            """)
            if result is None:
                raise NoSuchElementException(f"Element not found: LINK_TEXT={value}")
            return BotElement(result, self)
        elif by == By.PARTIAL_LINK_TEXT:
            escaped = value.replace('\\', '\\\\').replace('`', '\\`').replace('${', '\\${')
            result = self.bot_driver.run_js(f"""
                var links = document.querySelectorAll('a');
                var text = `{escaped}`;
                for (var i = 0; i < links.length; i++) {{
                    if (links[i].textContent.indexOf(text) !== -1) return links[i];
                }}
                return null;
            """)
            if result is None:
                raise NoSuchElementException(f"Element not found: PARTIAL_LINK_TEXT={value}")
            return BotElement(result, self)
        else:
            css = _by_to_css(by, value)
            try:
                el = self.bot_driver.select(css)
                return BotElement(el, self)
            except Exception:
                raise NoSuchElementException(f"Element not found: {by}={value}")

    def find_elements(self, by, value):
        """Selenium uyumlu find_elements"""
        if by == By.XPATH:
            escaped = value.replace('\\', '\\\\').replace('`', '\\`').replace('${', '\\${')
            results = self.bot_driver.run_js(f"""
                var xpath = `{escaped}`;
                var result = document.evaluate(xpath, document, null,
                    XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
                var nodes = [];
                for (var i = 0; i < result.snapshotLength; i++) {{
                    nodes.push(result.snapshotItem(i));
                }}
                return nodes;
            """)
            return [BotElement(r, self) for r in (results or [])]
        elif by == By.LINK_TEXT:
            escaped = value.replace('\\', '\\\\').replace('`', '\\`').replace('${', '\\${')
            results = self.bot_driver.run_js(f"""
                var links = document.querySelectorAll('a');
                var text = `{escaped}`;
                var matches = [];
                for (var i = 0; i < links.length; i++) {{
                    if (links[i].textContent.trim() === text) matches.push(links[i]);
                }}
                return matches;
            """)
            return [BotElement(r, self) for r in (results or [])]
        elif by == By.PARTIAL_LINK_TEXT:
            escaped = value.replace('\\', '\\\\').replace('`', '\\`').replace('${', '\\${')
            results = self.bot_driver.run_js(f"""
                var links = document.querySelectorAll('a');
                var text = `{escaped}`;
                var matches = [];
                for (var i = 0; i < links.length; i++) {{
                    if (links[i].textContent.indexOf(text) !== -1) matches.push(links[i]);
                }}
                return matches;
            """)
            return [BotElement(r, self) for r in (results or [])]
        else:
            css = _by_to_css(by, value)
            try:
                elements = self.bot_driver.select_all(css)
                return [BotElement(e, self) for e in elements]
            except Exception:
                return []

    def execute_script(self, script, *args):
        """Selenium uyumlu execute_script - arguments[N] referanslarını Botasaurus uyumlu hale getirir.

        Botasaurus run_js, argümanları JSON.parse ile işler → Element nesneleri JSON serializable
        olmadığı için hata verir. Bu metod:
        - Tüm non-element değerleri (string/number/bool) JS koduna direkt embed eder
        - Element argümanı varsa, ilk element'in apply() metodunu kullanır (CDP call_function_on)
        - apply() element'i 'element' değişkeni olarak JS'e geçirir, biz bunu arguments[0] yerine kullanırız
        """
        if not args:
            return self.bot_driver.run_js(script)

        # Argümanları ayır: element vs değer
        element_args = []  # (original_index, bot_element) tuples
        value_replacements = {}  # index -> js_literal

        for i, arg in enumerate(args):
            if isinstance(arg, BotElement):
                element_args.append((i, arg._el))
            else:
                # String/number/bool/None değerleri JS literaline çevir
                if isinstance(arg, str):
                    escaped = arg.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r')
                    js_val = f"'{escaped}'"
                elif isinstance(arg, bool):
                    js_val = 'true' if arg else 'false'
                elif isinstance(arg, (int, float)):
                    js_val = str(arg)
                elif arg is None:
                    js_val = 'null'
                else:
                    js_val = json.dumps(arg)
                value_replacements[i] = js_val

        # Önce value argümanlarını script'e embed et (büyük index'ten küçüğe)
        modified_script = script
        for i in sorted(value_replacements.keys(), reverse=True):
            modified_script = modified_script.replace(f'arguments[{i}]', value_replacements[i])

        if not element_args:
            # Element yok, sadece değerler inline edildi
            return self.bot_driver.run_js(modified_script)

        if len(element_args) == 1:
            # Tek element: apply() kullan - element 'element' olarak JS'e geçer
            el_idx, bot_el = element_args[0]
            # arguments[el_idx] referansını 'element' ile değiştir (apply bunu sağlar)
            modified_script = modified_script.replace(f'arguments[{el_idx}]', 'element')
            # apply() script'i otomatik (el) => { ... } fonksiyonuna sarar
            # ve element'i CDP call_function_on ile geçirir
            try:
                return bot_el.apply(modified_script)
            except Exception:
                # apply başarısız olursa, run_js ile element'i args listesi olarak geçirmeyi dene
                # (bazı botasaurus sürümleri bunu destekleyebilir)
                try:
                    modified_script2 = script
                    for i in sorted(value_replacements.keys(), reverse=True):
                        modified_script2 = modified_script2.replace(f'arguments[{i}]', value_replacements[i])
                    modified_script2 = modified_script2.replace(f'arguments[{el_idx}]', 'element')
                    return bot_el.run_js(modified_script2)
                except Exception:
                    return None
        else:
            # Birden fazla element: ilk element'in apply() metodunu kullan,
            # diğer elementleri document.querySelector ile bulmaya çalış
            # Bu durum nadir, ama yine de destekleyelim
            primary_idx, primary_el = element_args[0]
            modified_script = modified_script.replace(f'arguments[{primary_idx}]', 'element')
            # Diğer element argümanları için uyarı ver - tek element senaryosu en yaygın
            for el_idx, bot_el in element_args[1:]:
                modified_script = modified_script.replace(f'arguments[{el_idx}]', 'element')
            try:
                return primary_el.apply(modified_script)
            except Exception:
                return None

    def maximize_window(self):
        """Pencereyi maximize et"""
        try:
            self.bot_driver.run_js("""
                window.moveTo(0, 0);
                window.resizeTo(screen.availWidth, screen.availHeight);
            """)
        except Exception:
            pass

    def start_keep_maximize(self):
        """Sürekli maximize state'i koru (eski maximize_chrome davranışı)"""
        def _keep_maximize():
            while True:
                try:
                    self.maximize_window()
                except Exception:
                    break
                time.sleep(2)
        self._maximize_thread = threading.Thread(target=_keep_maximize, daemon=True)
        self._maximize_thread.start()

    def save_screenshot(self, filename):
        """Ekran görüntüsü kaydet"""
        try:
            self.bot_driver.save_screenshot(filename)
        except Exception:
            pass

    def implicitly_wait(self, seconds):
        """Selenium implicit wait uyumluluğu - no-op (botasaurus kendi wait'ini kullanır)"""
        pass

    def set_page_load_timeout(self, seconds):
        """Selenium page load timeout uyumluluğu - no-op"""
        pass

    def delete_all_cookies(self):
        """Tüm cookie'leri sil"""
        try:
            self.bot_driver.delete_cookies()
        except Exception:
            pass

    def quit(self):
        """Tarayıcıyı kapat"""
        try:
            self.bot_driver.close()
        except Exception:
            pass

    def close(self):
        """Tarayıcıyı kapat (quit ile aynı)"""
        self.quit()

    @property
    def browser_pid(self):
        """Browser PID - bring_chrome_to_front için"""
        try:
            return self.bot_driver.run_js("return null")  # Botasaurus PID'ye direkt erişim sağlamıyor
        except Exception:
            return None
