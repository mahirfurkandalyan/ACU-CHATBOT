"""
scraper/bologna_scraper.py
───────────────────────────
Acıbadem Üniversitesi Bologna Bilgi Paketi (OBS) scraper.
URL: https://obs.acibadem.edu.tr/oibs/bologna/index.aspx

Bu site ASP.NET tabanlı ve içerik JavaScript ile yüklenir.
Bu yüzden Selenium ile headless Chrome kullanılır.

Çekilen veriler:
  - Kurumsal Bilgiler (Yönetim, Üniversite Hakkında, Bologna Komisyonu, İletişim, AKTS)
  - Akademik Birimler: Ön Lisans / Lisans / Yüksek Lisans / Doktora programları
    → Her program için: adı, kodu, bölüm bilgisi, AKTS kredisi
    → Her program içinde ders listesi (kod, ad, kredi, AKTS, dönem, zorunlu/seçmeli)
  - Öğrenciler İçin Genel Bilgiler (Kampüs, Şehir, Konaklama, Sağlık vb.)
  - Erasmus Beyannamesi
  - Bologna Süreci

Çalıştırma:
    python scraper/bologna_scraper.py
    python scraper/bologna_scraper.py --lang en   # İngilizce versiyon
    python scraper/bologna_scraper.py --lang both  # Her ikisi
"""

import os
import sys
import time
import logging
import argparse
import django
from urllib.parse import urljoin, urlparse, parse_qs

import requests

# ── Django kurulumu ────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from chat.models import UniversityContent, Faculty, Department, Course, ScraperLog
from scraper.bs4_scraper import clean_text, save_content

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

# ── Selenium import ─────────────────────────────────────────────────────────────
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait, Select
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException, NoSuchElementException,
        StaleElementReferenceException, ElementNotInteractableException,
    )
    from bs4 import BeautifulSoup
except ImportError as e:
    log.error("Eksik bağımlılık: %s  →  pip install selenium webdriver-manager beautifulsoup4", e)
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Sabitler
# ─────────────────────────────────────────────────────────────────────────────

BOLOGNA_BASE = "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx"
BOLOGNA_ROOT = "https://obs.acibadem.edu.tr/oibs/bologna/"
PAGE_WAIT    = 15   # saniye – eleman bekleme limiti
CLICK_DELAY  = 1.5  # tıklama sonrası bekleme
SCROLL_PAUSE = 0.8
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ACU-ChatBot-Bologna-Scraper/1.0)"
}

# Menü yapısı: (menü metni, kategori, dil-bağımsız anahtar)
MENU_STRUCTURE = {
    "tr": {
        "kurumsal": [
            ("Yönetim",                "other"),
            ("Üniversite Hakkında",    "other"),
            ("Bologna Komisyonu",      "other"),
            ("İletişim",              "contact"),
            ("AKTS Kataloğu",         "academic"),
        ],
        "akademik": [
            ("Ön Lisans",      "academic"),
            ("Lisans",         "academic"),
            ("Yüksek Lisans",  "academic"),
            ("Doktora",        "academic"),
        ],
        "ogrenci": [
            ("Şehir Hakkında",           "campus"),
            ("Kampüs",                   "campus"),
            ("Yemek",                    "campus"),
            ("Sağlık Hizmetleri",        "campus"),
            ("Spor ve Sosyal Yaşam",     "campus"),
            ("Öğrenci Kulüpleri",        "campus"),
            ("Konaklama",                "campus"),
            ("Engelli Öğrenci Hizmetleri", "campus"),
        ],
        "erasmus": [
            ("Erasmus+ Beyannamesi",  "other"),
        ],
        "bologna": [
            ("Bologna Süreci",  "other"),
        ],
    },
    "en": {
        "kurumsal": [
            ("Management",                "other"),
            ("About University",          "other"),
            ("Bologna Commission",        "other"),
            ("Contact",                   "contact"),
            ("ECTS Catalogue",            "academic"),
        ],
        "akademik": [
            ("Associate Degree",  "academic"),
            ("Bachelor's Degree", "academic"),
            ("Master's Degree",   "academic"),
            ("PhD",               "academic"),
        ],
        "ogrenci": [
            ("About the City",            "campus"),
            ("Campus",                    "campus"),
            ("Food",                      "campus"),
            ("Health Services",           "campus"),
            ("Sports and Social Life",    "campus"),
            ("Student Clubs",             "campus"),
            ("Accommodation",             "campus"),
            ("Disabled Student Services", "campus"),
        ],
        "erasmus": [
            ("Erasmus+ Charter",  "other"),
        ],
        "bologna": [
            ("Bologna Process",  "other"),
        ],
    },
}

ACADEMIC_TYPE_MAP = {
    "tr": {
        "Ön Lisans": "myo",
        "Lisans": "lis",
        "Yüksek Lisans": "yls",
        "Doktora": "dok",
    },
    "en": {
        "Associate Degree": "myo",
        "Bachelor's Degree": "lis",
        "Master's Degree": "yls",
        "PhD": "dok",
    },
}

DYN_PAGE_MAP = {
    "tr": {
        "Yönetim": 100,
        "Üniversite Hakkında": 101,
        "Bologna Komisyonu": 102,
        "İletişim": 103,
        "AKTS Kataloğu": 104,
        "Şehir Hakkında": 300,
        "Kampüs": 301,
        "Yemek": 302,
        "Sağlık Hizmetleri": 303,
        "Spor ve Sosyal Yaşam": 304,
        "Öğrenci Kulüpleri": 305,
        "Konaklama": 309,
        "Engelli Öğrenci Hizmetleri": 311,
        "Erasmus+ Beyannamesi": 401,
        "Bologna Süreci": 400,
    },
    "en": {
        "Management": 100,
        "About University": 101,
        "Bologna Commission": 102,
        "Contact": 103,
        "ECTS Catalogue": 104,
        "About the City": 300,
        "Campus": 301,
        "Food": 302,
        "Health Services": 303,
        "Sports and Social Life": 304,
        "Student Clubs": 305,
        "Accommodation": 309,
        "Disabled Student Services": 311,
        "Erasmus+ Charter": 401,
        "Bologna Process": 400,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────────────

def build_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=tr-TR")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    # Selenium Manager'ı öncele; çoğu modern kurulumda driver'ı kendisi çözer.
    try:
        return webdriver.Chrome(options=opts)
    except Exception as exc:
        log.warning("Yerel Selenium Manager ile Chrome açılamadı: %s", exc)

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=opts)
    except ImportError:
        return webdriver.Chrome(options=opts)


def wait_for(driver, css: str, timeout: int = PAGE_WAIT):
    try:
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css))
        )
    except TimeoutException:
        return None


def scroll_page(driver):
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(SCROLL_PAUSE)
    driver.execute_script("window.scrollTo(0, 0);")


def get_page_text(driver) -> str:
    """Sayfanın görünür metin içeriğini döndürür (nav/script hariç)."""
    soup = BeautifulSoup(driver.page_source, "html.parser")
    for tag in soup.find_all(["nav", "script", "style", "noscript", "header", "footer"]):
        tag.decompose()
    main = soup.find("div", id=lambda x: x and "icerik" in x.lower())
    if not main:
        main = soup.find("main") or soup.find("div", class_=lambda c: c and "content" in c.lower())
    if not main:
        main = soup.find("body")
    return clean_text(main.get_text(separator=" ")) if main else ""


# ─────────────────────────────────────────────────────────────────────────────
# Menü tıklama yardımcıları
# ─────────────────────────────────────────────────────────────────────────────

def click_menu_item(driver, link_text: str) -> bool:
    """
    Navbarda verilen metni içeren linki bulup tıklar.
    Exact match, sonra partial match dener.
    """
    # Önce tam eşleşme dene
    for by, val in [
        (By.LINK_TEXT, link_text),
        (By.PARTIAL_LINK_TEXT, link_text[:15]),
        (By.XPATH, f"//a[contains(normalize-space(.), '{link_text[:20]}')]"),
    ]:
        try:
            el = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((by, val)))
            driver.execute_script("arguments[0].scrollIntoView(true);", el)
            time.sleep(0.3)
            el.click()
            time.sleep(CLICK_DELAY)
            return True
        except (TimeoutException, NoSuchElementException, StaleElementReferenceException,
                ElementNotInteractableException):
            continue
    log.warning("Menü öğesi bulunamadı: '%s'", link_text)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Akademik birim tarayıcısı (Ön Lisans / Lisans / YL / Doktora)
# ─────────────────────────────────────────────────────────────────────────────

def scrape_academic_level(driver, level_text: str, lang: str) -> int:
    """
    Bir akademik seviye (Lisans vb.) menüsüne tıklar.
    Açılan program listesini iter eder, her programın ders listesini çeker.
    """
    saved = 0
    base_url = f"{BOLOGNA_BASE}?lang={lang}"

    if not click_menu_item(driver, level_text):
        return 0

    time.sleep(2)

    # Program seçme dropdown var mı?
    program_select = None
    for sel_id in ["ctl00_ContentPlaceHolder1_ddlBirim", "ddlBirim", "ddlProgram",
                   "ctl00_ContentPlaceHolder1_ddlProgram"]:
        try:
            program_select = Select(driver.find_element(By.ID, sel_id))
            log.info("Program dropdown bulundu: id=%s (%d seçenek)", sel_id, len(program_select.options))
            break
        except NoSuchElementException:
            continue

    if program_select:
        # Dropdown'daki her programı tara
        option_count = len(program_select.options)
        for i in range(1, option_count):   # 0 = "Seçiniz" satırı
            try:
                # Her iterasyonda dropdown'u yeniden bul (DOM yenilenebilir)
                select_el = None
                for sel_id in ["ctl00_ContentPlaceHolder1_ddlBirim", "ddlBirim", "ddlProgram",
                               "ctl00_ContentPlaceHolder1_ddlProgram"]:
                    try:
                        select_el = Select(driver.find_element(By.ID, sel_id))
                        break
                    except NoSuchElementException:
                        continue
                if not select_el:
                    break

                opt = select_el.options[i]
                prog_name  = clean_text(opt.text)
                prog_value = opt.get_attribute("value")

                if not prog_name or prog_name.lower() in ("seçiniz", "select"):
                    continue

                log.info("  Program: %s", prog_name)
                select_el.select_by_index(i)
                time.sleep(2)

                # Ders tablosunu çek
                saved += _extract_program_courses(driver, prog_name, level_text, lang)

            except (StaleElementReferenceException, Exception) as exc:
                log.debug("Program iterasyon hatası (i=%d): %s", i, exc)
                continue
    else:
        # Dropdown yok; sayfanın genel içeriğini kaydet
        text = get_page_text(driver)
        if text:
            title = f"{level_text} – Programlar"
            url   = driver.current_url
            save_content(title, text, url, "academic")
            saved += 1

    return saved


def _extract_program_courses(driver, prog_name: str, level: str, lang: str) -> int:
    """
    Aktif program sayfasından ders tablosunu çeker.
    Dersleri hem Course modeline hem de UniversityContent'e kaydeder.
    """
    saved = 0
    url   = driver.current_url

    # Ders tablosu seçicileri (site yapısına göre)
    TABLE_SELECTORS = [
        "table.ders-tablosu",
        "table.table",
        "#ctl00_ContentPlaceHolder1_gvDersler",
        "table",
    ]

    soup = BeautifulSoup(driver.page_source, "html.parser")
    table = None
    for sel in TABLE_SELECTORS:
        table = soup.select_one(sel)
        if table:
            break

    if not table:
        # Tablo yoksa sayfanın tüm metnini kaydet
        text = get_page_text(driver)
        if text:
            save_content(f"{level}: {prog_name}", text, url, "academic")
            saved += 1
        return saved

    rows = table.find_all("tr")
    header = [clean_text(th.get_text()) for th in (rows[0].find_all("th") if rows else [])]
    log.debug("Tablo başlıkları: %s", header)

    # Başlık sütunlarını tahmin et
    def col_index(keywords):
        for i, h in enumerate(header):
            if any(k in h.lower() for k in keywords):
                return i
        return None

    idx_code   = col_index(["kod", "code"])
    idx_name   = col_index(["ad", "name", "ders", "course"])
    idx_akts   = col_index(["akts", "ects"])
    idx_kredi  = col_index(["kredi", "credit"])
    idx_donem  = col_index(["dönem", "semester", "yarıyıl"])
    idx_tur    = col_index(["tür", "type", "zorunlu", "seçmeli"])

    course_lines = []

    for row in rows[1:]:
        cols = row.find_all(["td", "th"])
        if len(cols) < 2:
            continue

        def cell(idx):
            if idx is not None and idx < len(cols):
                return clean_text(cols[idx].get_text())
            return ""

        code   = cell(idx_code)
        name   = cell(idx_name) or cell(1)
        akts   = cell(idx_akts)
        kredi  = cell(idx_kredi)
        donem  = cell(idx_donem)
        tur    = cell(idx_tur)

        if not name:
            continue

        # Faculty / Department bul veya oluştur
        faculty, _ = Faculty.objects.get_or_create(
            name=prog_name,
            defaults={"url": url},
        )
        dept, _ = Department.objects.get_or_create(
            faculty=faculty,
            name=f"{level} – {prog_name}",
            defaults={"url": url},
        )

        # Course modeline kaydet
        try:
            credits_int = int(kredi) if kredi and kredi.isdigit() else None
        except ValueError:
            credits_int = None

        Course.objects.update_or_create(
            code=code,
            name=name,
            defaults={
                "department":  dept,
                "description": f"AKTS: {akts}  Tür: {tur}",
                "credits":     credits_int,
                "semester":    donem,
                "url":         url,
            },
        )

        line = f"Kod: {code} | Ders: {name} | AKTS: {akts} | Kredi: {kredi} | Dönem: {donem} | Tür: {tur}"
        course_lines.append(line.strip(" |"))

    if course_lines:
        content = f"Program: {prog_name}\nSeviye: {level}\n\n" + "\n".join(course_lines)
        save_content(f"Ders Listesi – {prog_name}", content, url, "course")
        saved += 1
        log.info("    %d ders kaydedildi.", len(course_lines))

    return saved


# ─────────────────────────────────────────────────────────────────────────────
# Genel içerik sayfası tarayıcısı
# ─────────────────────────────────────────────────────────────────────────────

def scrape_info_page(driver, page_name: str, category: str, lang: str) -> int:
    """
    Kurumsal veya öğrenci bilgisi sayfasını açar ve içeriği kaydeder.
    """
    if not click_menu_item(driver, page_name):
        return 0

    time.sleep(1.5)
    scroll_page(driver)

    title   = f"{page_name}"
    content = get_page_text(driver)
    url     = driver.current_url

    if not content or len(content) < 40:
        log.debug("Boş sayfa: %s", page_name)
        return 0

    save_content(title, content, url, category)
    log.info("Kaydedildi: %s (%d karakter)", page_name, len(content))
    return 1


def fetch_soup(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as exc:
        log.warning("OBS sayfası alınamadı: %s – %s", url, exc)
        return None


def soup_text(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    return clean_text((soup.find("body") or soup).get_text(separator=" "))


def parse_program_links(level_code: str, lang: str) -> list[dict]:
    url = f"{BOLOGNA_ROOT}unitSelection.aspx?type={level_code}&lang={lang}"
    soup = fetch_soup(url)
    if not soup:
        return []

    programs = []
    for panel in soup.select("div.panel"):
        heading = panel.select_one(".panel-title")
        faculty_name = clean_text(heading.get_text(" ")) if heading else "Bilinmeyen Fakülte"
        for link in panel.select("ul.list-group li a[href*='curOp=showPac']"):
            href = urljoin(url, link.get("href"))
            program_name = clean_text(link.get_text(" "))
            query = parse_qs(urlparse(href).query)
            cur_sunit = query.get("curSunit", [""])[0]
            if not program_name or not cur_sunit:
                continue
            programs.append(
                {
                    "faculty_name": faculty_name,
                    "program_name": program_name,
                    "cur_sunit": cur_sunit,
                    "program_url": href,
                }
            )
    return programs


def scrape_program_requests(program: dict, level_text: str, lang: str) -> int:
    saved = 0
    faculty, _ = Faculty.objects.get_or_create(
        name=program["faculty_name"],
        defaults={"url": program["program_url"]},
    )
    department, _ = Department.objects.get_or_create(
        faculty=faculty,
        name=program["program_name"],
        defaults={"url": program["program_url"]},
    )

    about_url = f"{BOLOGNA_ROOT}progAbout.aspx?lang={lang}&curSunit={program['cur_sunit']}"
    about_soup = fetch_soup(about_url)
    if about_soup:
        text = soup_text(about_soup)
        if text:
            save_content(f"Program Hakkında – {program['program_name']}", text, about_url, "academic")
            saved += 1

    officials_url = f"{BOLOGNA_ROOT}progOfficials.aspx?lang={lang}&curSunit={program['cur_sunit']}"
    officials_soup = fetch_soup(officials_url)
    if officials_soup:
        text = soup_text(officials_soup)
        if text:
            save_content(f"Program Yetkilileri – {program['program_name']}", text, officials_url, "faculty")
            saved += 1

    staff_url = f"{BOLOGNA_ROOT}progAcademicStaff.aspx?lang={lang}&curSunit={program['cur_sunit']}"
    staff_soup = fetch_soup(staff_url)
    if staff_soup:
        text = soup_text(staff_soup)
        if text:
            save_content(f"Akademik Personel – {program['program_name']}", text, staff_url, "faculty")
            saved += 1

    courses_url = f"{BOLOGNA_ROOT}progCourses.aspx?lang={lang}&curSunit={program['cur_sunit']}"
    courses_soup = fetch_soup(courses_url)
    if not courses_soup:
        return saved

    course_lines = []
    current_semester = ""
    for table in courses_soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue
        for row in rows:
            cells = [clean_text(cell.get_text(" ")) for cell in row.find_all(["td", "th"])]
            cells = [cell for cell in cells if cell]
            if not cells:
                continue
            if len(cells) == 1 and "Ders Planı" in cells[0]:
                current_semester = cells[0]
                continue
            if "Ders Kodu" in " ".join(cells):
                continue
            if len(cells) >= 6:
                code = cells[0]
                name = cells[1]
                t_u_l = cells[2] if len(cells) > 2 else ""
                course_type = cells[3] if len(cells) > 3 else ""
                akts = cells[4] if len(cells) > 4 else ""
                teaching_mode = cells[6] if len(cells) > 6 else ""
                credits = int(akts) if akts.isdigit() else None

                Course.objects.update_or_create(
                    code=code,
                    name=name,
                    defaults={
                        "department": department,
                        "description": f"T+U+L: {t_u_l} | Tür: {course_type} | Öğretim Şekli: {teaching_mode}",
                        "credits": credits,
                        "semester": current_semester,
                        "url": courses_url,
                    },
                )
                course_lines.append(
                    f"Dönem: {current_semester} | Kod: {code} | Ders: {name} | T+U+L: {t_u_l} | Tür: {course_type} | AKTS: {akts} | Öğretim Şekli: {teaching_mode}"
                )

    if course_lines:
        save_content(
            f"Ders Listesi – {program['program_name']}",
            "\n".join(course_lines),
            courses_url,
            "course",
        )
        saved += 1
        log.info("Program işlendi: %s (%d ders)", program["program_name"], len(course_lines))

    return saved


# ─────────────────────────────────────────────────────────────────────────────
# Ana çalıştırıcı
# ─────────────────────────────────────────────────────────────────────────────

def run_bologna_scraper(lang: str = "tr") -> int:
    """
    Bologna OBS sitesini baştan sona tarar.
    lang: 'tr' veya 'en'
    """
    url = f"{BOLOGNA_BASE}?lang={lang}"
    log.info("Bologna OBS scraper başlatılıyor → %s", url)

    total  = 0
    start  = time.time()

    try:
        menu = MENU_STRUCTURE.get(lang, MENU_STRUCTURE["tr"])

        log.info("─── OBS Bilgi Sayfaları ───")
        info_sections = menu["kurumsal"] + menu["ogrenci"] + menu["erasmus"] + menu["bologna"]
        for page_name, category in info_sections:
            cur_page_id = DYN_PAGE_MAP.get(lang, DYN_PAGE_MAP["tr"]).get(page_name)
            if not cur_page_id:
                continue
            info_url = f"{BOLOGNA_ROOT}dynConPage.aspx?curPageId={cur_page_id}&lang={lang}"
            soup = fetch_soup(info_url)
            if not soup:
                continue
            text = soup_text(soup)
            if text:
                save_content(page_name, text, info_url, category)
                total += 1

        log.info("─── OBS Akademik Birimler ───")
        for level_text, _ in menu["akademik"]:
            level_code = ACADEMIC_TYPE_MAP.get(lang, ACADEMIC_TYPE_MAP["tr"]).get(level_text)
            if not level_code:
                continue
            programs = parse_program_links(level_code, lang)
            log.info("%s için %d program bulundu.", level_text, len(programs))
            for program in programs:
                total += scrape_program_requests(program, level_text, lang)

        ScraperLog.objects.create(
            url=url,
            status="success" if total > 0 else "partial",
            records_saved=total,
            duration_seconds=time.time() - start,
        )

    except Exception as exc:
        log.error("Bologna scraper genel hata: %s", exc, exc_info=True)
        ScraperLog.objects.create(
            url=url, status="failed",
            error_message=str(exc),
            duration_seconds=time.time() - start,
        )

    log.info("Bologna OBS tamamlandı. Toplam %d kayıt (%s).", total, lang.upper())
    return total


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ACU Bologna OBS Scraper")
    parser.add_argument(
        "--lang",
        choices=["tr", "en", "both"],
        default="tr",
        help="Hangi dil versiyonu taransın? (varsayılan: tr)",
    )
    args = parser.parse_args()

    if args.lang == "both":
        run_bologna_scraper("tr")
        run_bologna_scraper("en")
    else:
        run_bologna_scraper(args.lang)
