import re
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings
from django.db.models import Q

from .models import Course, Department, Faculty, UniversityContent


STOP_WORDS = {
    "acibadem",
    "acıbadem",
    "universitesi",
    "üniversitesi",
    "universite",
    "üniversite",
    "hakkinda",
    "hakkında",
    "bilgi",
    "verir",
    "misin",
    "mısın",
    "nedir",
    "hangi",
    "olan",
    "icin",
    "için",
    "ile",
    "ve",
    "veya",
    "ama",
    "gibi",
    "bir",
    "bu",
    "da",
    "de",
    "mi",
    "mı",
    "mu",
    "mü",
    "dersleri",
    "dersler",
    "şartları",
    "sartlari",
    "nelerdir",
    "neler",
    "nerede",
    "nasıl",
    "nasil",
    "var",
    "programı",
    "programi",
}

CATEGORY_HINTS = {
    "admission": {"başvuru", "basvuru", "kayıt", "kayit", "kabul", "burs", "ücret", "ucret"},
    "course": {"ders", "müfredat", "mufredat", "course", "akts", "ects", "credit", "kredi"},
    "campus": {"kampüs", "kampus", "yurt", "konaklama", "yemek", "ulaşım", "ulasim"},
    "contact": {"iletişim", "iletisim", "telefon", "mail", "e-posta", "adres"},
    "academic": {"program", "bölüm", "bolum", "lisans", "yüksek lisans", "doktora"},
    "faculty": {"fakülte", "fakulte", "bölüm başkanı", "bolum baskani", "başkan", "baskan", "dekan", "yetkili", "akademik personel", "kadro"},
    "research": {"araştırma", "arastirma", "laboratuvar", "proje", "merkez"},
    "news": {"duyuru", "haber", "etkinlik"},
}


@dataclass
class RetrievedChunk:
    title: str
    body: str
    source_type: str
    url: str = ""
    category: str = "other"
    language: str = "tr"
    score: int = 0
    matched_tokens: int = 0


def normalize_text(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"[^\w\sçğıöşü]", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def tokenize_query(question: str) -> list[str]:
    normalized = normalize_text(question)
    tokens = []
    for token in normalized.split():
        if len(token) < 3 or token in STOP_WORDS:
            continue
        tokens.append(token)
    return tokens


def detect_category(question: str) -> str | None:
    normalized = normalize_text(question)
    if any(hint in normalized for hint in ["bölüm başkanı", "bolum baskani", "başkan", "baskan", "dekan", "yetkili", "akademik personel", "kadro"]):
        return "faculty"
    for category, hints in CATEGORY_HINTS.items():
        if any(hint in normalized for hint in hints):
            return category
    return None


def score_text(text: str, title: str, tokens: list[str]) -> int:
    haystack = normalize_text(text)
    normalized_title = normalize_text(title)
    score = 0

    for token in tokens:
        if token in normalized_title:
            score += 5
        occurrences = haystack.count(token)
        if occurrences:
            score += min(occurrences, 5) * 2

    if tokens:
        joined = " ".join(tokens)
        if joined in haystack:
            score += 6
        if joined in normalized_title:
            score += 10

    return score


def count_matched_tokens(text: str, title: str, tokens: list[str]) -> int:
    haystack = normalize_text(text)
    normalized_title = normalize_text(title)
    return sum(1 for token in tokens if token in haystack or token in normalized_title)


def trim_text(text: str, limit: int = 350) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_break = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    if last_break > int(limit * 0.6):
        return cut[: last_break + 1]
    return cut + "..."


def retrieve_context(question: str, language: str = "tr", limit: int = 6) -> list[RetrievedChunk]:
    tokens = tokenize_query(question)
    category = detect_category(question)
    chunks: list[RetrievedChunk] = []

    content_query = UniversityContent.objects.filter(is_active=True)
    if language:
        content_query = content_query.filter(language=language)
    base_content_query = content_query

    if tokens:
        content_filter = Q()
        for token in tokens:
            content_filter |= Q(title__icontains=token) | Q(content__icontains=token)
        content_query = content_query.filter(content_filter)
        if category:
            filtered_with_category = content_query.filter(category=category)
            if filtered_with_category.exists():
                content_query = filtered_with_category
    elif category:
        content_query = content_query.filter(category=category)

    if not content_query.exists():
        content_query = base_content_query
        if tokens:
            content_filter = Q()
            for token in tokens:
                content_filter |= Q(title__icontains=token) | Q(content__icontains=token)
            content_query = content_query.filter(content_filter)

    for item in content_query[:200]:
        score = score_text(item.content, item.title, tokens)
        matched_tokens = count_matched_tokens(item.content, item.title, tokens)
        if category and item.category == category:
            score += 4
        if score <= 0 and tokens:
            continue
        if len(tokens) >= 2 and matched_tokens < 2 and score < 15:
            continue
        chunks.append(
            RetrievedChunk(
                title=item.title,
                body=trim_text(item.content),
                source_type="university_content",
                url=item.url,
                category=item.category,
                language=item.language,
                score=score or 1,
                matched_tokens=matched_tokens,
            )
        )

    if tokens:
        faculty_filter = Q()
        department_filter = Q()
        course_filter = Q()
        for token in tokens:
            faculty_filter |= Q(name__icontains=token) | Q(description__icontains=token)
            department_filter |= Q(name__icontains=token) | Q(description__icontains=token)
            course_filter |= (
                Q(code__icontains=token)
                | Q(name__icontains=token)
                | Q(description__icontains=token)
                | Q(semester__icontains=token)
            )

        for faculty in Faculty.objects.filter(faculty_filter)[:10]:
            body = faculty.description or f"{faculty.name} hakkında kayıt bulundu."
            matched_tokens = count_matched_tokens(body, faculty.name, tokens)
            score = score_text(body, faculty.name, tokens) + 3
            if len(tokens) >= 2 and matched_tokens < 2 and score < 15:
                continue
            chunks.append(
                RetrievedChunk(
                    title=faculty.name,
                    body=trim_text(body),
                    source_type="faculty",
                    url=faculty.url,
                    category="faculty",
                    score=score,
                    matched_tokens=matched_tokens,
                )
            )

        for department in Department.objects.select_related("faculty").filter(department_filter)[:10]:
            body = department.description or f"{department.name}, {department.faculty.name} bünyesindedir."
            matched_tokens = count_matched_tokens(body, department.name, tokens)
            score = score_text(body, department.name, tokens) + 4
            if len(tokens) >= 2 and matched_tokens < 2 and score < 15:
                continue
            chunks.append(
                RetrievedChunk(
                    title=f"{department.faculty.name} / {department.name}",
                    body=trim_text(body),
                    source_type="department",
                    url=department.url,
                    category="academic",
                    score=score,
                    matched_tokens=matched_tokens,
                )
            )

        for course in Course.objects.select_related("department", "department__faculty").filter(course_filter)[:12]:
            dept_name = course.department.name if course.department else "Bölüm belirtilmemiş"
            faculty_name = (
                course.department.faculty.name
                if course.department and course.department.faculty
                else "Fakülte belirtilmemiş"
            )
            details = [
                course.code,
                course.name,
                f"Bölüm: {dept_name}",
                f"Fakülte: {faculty_name}",
                f"Kredi: {course.credits}" if course.credits else "",
                f"Dönem: {course.semester}" if course.semester else "",
                course.description,
            ]
            body = " | ".join(part for part in details if part)
            matched_tokens = count_matched_tokens(body, course.name, tokens)
            score = score_text(body, course.name, tokens) + 5
            if len(tokens) >= 2 and matched_tokens < 2 and score < 15:
                continue
            chunks.append(
                RetrievedChunk(
                    title=f"{course.code} {course.name}".strip(),
                    body=trim_text(body),
                    source_type="course",
                    url=course.url,
                    category="course",
                    score=score,
                    matched_tokens=matched_tokens,
                )
            )

    deduped: list[RetrievedChunk] = []
    seen_keys: set[tuple[str, str]] = set()
    for chunk in sorted(chunks, key=lambda item: item.score, reverse=True):
        key = (chunk.title, chunk.url or chunk.body[:80])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(chunk)
        if len(deduped) >= limit:
            break

    return deduped


def build_prompt(question: str, contexts: list[RetrievedChunk]) -> str:
    if contexts:
        context_blocks = []
        for index, item in enumerate(contexts, start=1):
            meta = [f"kaynak_tipi={item.source_type}", f"kategori={item.category}"]
            if item.url:
                meta.append(f"url={item.url}")
            block = (
                f"[Kaynak {index} | {' | '.join(meta)}]\n"
                f"Başlık: {item.title}\n"
                f"İçerik: {item.body}"
            )
            context_blocks.append(block)
        context_text = "\n\n".join(context_blocks)
    else:
        context_text = "İlgili kaynak bulunamadı."

    system = (
        "Acıbadem Üniversitesi bilgi asistanısın. "
        "Aşağıdaki kaynaklara dayanarak soruyu kısa ve net Türkçe yanıtla. "
        "Kaynaklarda olmayan bilgileri uydurma. "
        "Kaynak numarası veya [Kaynak N] gibi ifadeleri yanıta ekleme. "
        "Yeterli bilgi yoksa sadece 'Bu konuda yeterli bilgim bulunmuyor.' de."
    )
    user_message = (
        f"Bilgi kaynakları:\n{context_text}\n\n"
        f"Soru: {question}"
    )
    return f"<s>[INST] {system}\n\n{user_message} [/INST]"


def build_fallback_answer(contexts: list[RetrievedChunk]) -> str:
    if not contexts:
        return (
            "Bu konuda veritabanında yeterli bilgi bulamadım. "
            "Daha spesifik bölüm, ders, fakülte veya başvuru konusu belirtirsen tekrar deneyebilirim."
        )

    return (
        "Bu konuda yeterli ve doğrudan bilgi bulamadım. "
        "Daha spesifik bir bölüm, fakülte veya sayfa konusu belirtirsen tekrar deneyebilirim."
    )


def build_direct_answer(question: str, contexts: list[RetrievedChunk]) -> str | None:
    if not contexts:
        return None

    category = detect_category(question)
    tokens = tokenize_query(question)
    top = contexts[0]
    exact_phrase = " ".join(tokens[:2]) if len(tokens) >= 2 else (tokens[0] if tokens else "")

    if exact_phrase:
        for item in contexts:
            haystack = normalize_text(f"{item.title} {item.body}")
            if exact_phrase in haystack:
                top = item
                break

    full_body = top.body
    if top.source_type == "university_content" and top.url:
        full_record = UniversityContent.objects.filter(url=top.url).only("content").first()
        if full_record and full_record.content:
            full_body = full_record.content

    def strip_prefix(title: str, prefix: str) -> str:
        cleaned = re.sub(rf"^{re.escape(prefix)}\s*[-–—?:]\s*", "", title).strip()
        return cleaned if cleaned else title

    if category == "course" and top.category == "course":
        matches = re.findall(r"Kod:\s*([^|]+)\s*\|\s*Ders:\s*([^|]+)", full_body)
        unique_courses: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for code, name in matches:
            item = (code.strip(), name.strip())
            if item in seen:
                continue
            seen.add(item)
            unique_courses.append(item)
            if len(unique_courses) >= 8:
                break
        if unique_courses:
            program_name = strip_prefix(top.title, "Ders Listesi")
            lines = [f"{program_name} programında öne çıkan dersler:"]
            for code, name in unique_courses:
                lines.append(f"- {code}: {name}")
            return "\n".join(lines)

    if category == "academic" and top.title.startswith("Program Hakkında"):
        program_name = strip_prefix(top.title, "Program Hakkında")
        body_clean = re.sub(r"https?://\S+", "", full_body).strip()
        return f"{program_name} programı hakkında:\n{trim_text(body_clean, 450)}"

    normalized_question = normalize_text(question)
    if any(keyword in normalized_question for keyword in ["baskan", "başkan", "dekan", "yetkili"]):
        if top.title.startswith("Program Yetkilileri"):
            program_name = strip_prefix(top.title, "Program Yetkilileri")
            cleaned = re.sub(r"https?://\S+", "", full_body).strip()
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return f"{program_name} bölümü yetkilileri:\n{trim_text(cleaned, 300)}"

    return None


def sanitize_answer(answer: str) -> str:
    answer = re.sub(r"\[Kaynak\s*\d+\]", "", answer, flags=re.IGNORECASE)
    answer = re.sub(r"Kaynak\s*\d+", "", answer, flags=re.IGNORECASE)
    # Ollama'nın prompt'u tekrar etmesini engelle
    answer = re.sub(r"(kaynak_tipi|kategori|url)=\S+", "", answer, flags=re.IGNORECASE)
    answer = re.sub(r"\[INST\].*?\[/INST\]", "", answer, flags=re.DOTALL)
    answer = re.sub(r"Bilgi kaynakları:.*?Soru:", "", answer, flags=re.DOTALL)
    answer = re.sub(r"\s{2,}", " ", answer).strip()
    return answer


def call_ollama(prompt: str) -> str:
    response = requests.post(
        f"{settings.OLLAMA_URL}/api/generate",
        json={
            "model": settings.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": 400,
            },
        },
        timeout=settings.OLLAMA_TIMEOUT,
    )
    response.raise_for_status()
    return (response.json().get("response") or "").strip()


def answer_question(question: str, language: str = "tr") -> dict[str, Any]:
    contexts = retrieve_context(question=question, language=language, limit=4)
    normalized_question = normalize_text(question)
    if contexts:
        if any(keyword in normalized_question for keyword in ["sart", "şart", "kosul", "koşul"]):
            evidence_found = any(
                any(keyword in normalize_text(f"{item.title} {item.body}") for keyword in ["sart", "şart", "kosul", "koşul"])
                for item in contexts
            )
            if not evidence_found:
                contexts = []

    if not contexts or max(item.score for item in contexts) < 8:
        answer = build_fallback_answer(contexts)
        return {
            "answer": answer,
            "sources": [
                {
                    "title": item.title,
                    "url": item.url,
                    "category": item.category,
                    "source_type": item.source_type,
                }
                for item in contexts
            ],
            "prompt": "",
        }

    direct_answer = build_direct_answer(question, contexts)
    if direct_answer:
        return {
            "answer": direct_answer,
            "sources": [
                {
                    "title": item.title,
                    "url": item.url,
                    "category": item.category,
                    "source_type": item.source_type,
                }
                for item in contexts
            ],
            "prompt": "",
        }

    prompt = build_prompt(question, contexts)

    try:
        answer = call_ollama(prompt)
        if not answer:
            answer = build_fallback_answer(contexts)
        else:
            answer = sanitize_answer(answer)
    except requests.exceptions.ConnectionError:
        answer = "Şu anda Ollama servisine ulaşılamıyor. Lütfen servis ayağa kalktıktan sonra tekrar deneyin."
    except requests.exceptions.Timeout:
        answer = "LLM yanıtı zaman aşımına uğradı. Daha kısa veya daha net bir soru ile tekrar deneyin."
    except requests.RequestException:
        answer = "AI servisi yanıt üretirken hata verdi. Lütfen daha sonra tekrar deneyin."

    return {
        "answer": answer,
        "sources": [
            {
                "title": item.title,
                "url": item.url,
                "category": item.category,
                "source_type": item.source_type,
            }
            for item in contexts
        ],
        "prompt": prompt,
    }
