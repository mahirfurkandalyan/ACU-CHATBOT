import json
import traceback
from collections import OrderedDict

from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt

from .models import ChatMessage, ChatSession, Department, UserProfile
from .services import answer_question, retrieve_context


def should_expand_with_context(question: str) -> bool:
    lowered = question.strip().lower()
    if len(lowered.split()) <= 4:
        return True
    follow_up_markers = [
        "kimdir",
        "kim",
        "bölüm başkanı",
        "bolum baskani",
        "dekan",
        "hangi ders",
        "kaç kredi",
        "kac kredi",
        "oryantasyon",
        "staj",
        "ücret",
        "ucret",
        "başvuru",
        "basvuru",
    ]
    return any(marker in lowered for marker in follow_up_markers)


PROGRAM_CATEGORY_ORDER = OrderedDict(
    [
        (
            "Lisans Programları",
            [
                "Tıp Fakültesi",
                "Eczacılık Fakültesi",
                "Sağlık Bilimleri Fakültesi",
                "İnsan ve Toplum Bilimleri Fakültesi",
                "Mühendislik ve Doğa Bilimleri Fakültesi",
            ],
        ),
        (
            "Ön Lisans Programları",
            [
                "Sağlık Hizmetleri Meslek Yüksekokulu",
                "Meslek Yüksekokulu",
            ],
        ),
        (
            "Lisansüstü Programlar",
            [
                "Sağlık Bilimleri Enstitüsü",
                "Sosyal Bilimler Enstitüsü",
                "Fen Bilimleri Enstitüsü",
                "Senoloji Araştırma Enstitüsü",
            ],
        ),
    ]
)

CANONICAL_PROGRAMS = {
    "Tıp Fakültesi": ["Tıp"],
    "Eczacılık Fakültesi": ["Eczacılık"],
    "Sağlık Bilimleri Fakültesi": [
        "Hemşirelik",
        "Hemşirelik (İngilizce)",
        "Fizyoterapi ve Rehabilitasyon",
        "Beslenme ve Diyetetik",
        "Beslenme ve Diyetetik (İngilizce)",
        "Sağlık Yönetimi",
    ],
    "İnsan ve Toplum Bilimleri Fakültesi": [
        "Psikoloji",
        "Psikoloji (İngilizce)",
        "Sosyoloji",
    ],
    "Mühendislik ve Doğa Bilimleri Fakültesi": [
        "Bilgisayar Mühendisliği (İngilizce)",
        "Biyomedikal Mühendisliği (İngilizce)",
        "Moleküler Biyoloji ve Genetik (İngilizce)",
    ],
    "Sağlık Hizmetleri Meslek Yüksekokulu": [
        "Ameliyathane Hizmetleri",
        "Anestezi",
        "Anestezi (İ.Ö.)",
        "Ağız ve Diş Sağlığı",
        "Ağız ve Diş Sağlığı (İ.Ö.)",
        "Diyaliz",
        "Elektronörofizyoloji",
        "Fizyoterapi",
        "Odyometri",
        "Optisyenlik",
        "Ortopedik Protez ve Ortez",
        "Patoloji Laboratuvar Teknikleri",
        "Patoloji Laboratuvar Teknikleri (İ.Ö.)",
        "Podoloji",
        "Podoloji (İ.Ö.)",
        "Radyoterapi",
        "Tıbbi Dokümantasyon ve Sekreterlik",
        "Tıbbi Dokümantasyon ve Sekreterlik (İ.Ö.)",
        "Tıbbi Görüntüleme Teknikleri",
        "Tıbbi Görüntüleme Teknikleri (İ.Ö.)",
        "Tıbbi Laboratuvar Teknikleri",
        "Tıbbi Laboratuvar Teknikleri (İ.Ö.)",
        "Tıbbi Veri İşleme Teknikerliği",
        "İlk ve Acil Yardım",
        "İlk ve Acil Yardım (İ.Ö.)",
    ],
    "Meslek Yüksekokulu": [
        "Aşçılık",
        "Bilgisayar Programcılığı",
        "Biyomedikal Cihaz Teknolojisi",
    ],
    "Sağlık Bilimleri Enstitüsü": [
        "Acil Hemşireliği Tezli Yüksek Lisans",
        "Adli Bilimler Tezli Yüksek Lisans",
        "Adli Bilimler Tezsiz Yüksek Lisans",
        "Anatomi (Tıp) Tezli Yüksek Lisans",
        "Beslenme ve Diyetetik Doktora",
        "Beslenme ve Diyetetik Tezli Yüksek Lisans",
        "Beslenme ve Diyetetik Tezsiz Yüksek Lisans",
        "Biyoetik Tezli Yüksek Lisans",
        "Biyofizik Doktora Programı (İngilizce)",
        "Biyofizik Tezli Yüksek Lisans Programı (İngilizce)",
        "Biyoistatistik ve Biyoinformatik Doktora (İngilizce)",
        "Biyoistatistik ve Biyoinformatik Tezli Yüksek Lisans (İngilizce)",
        "Biyokimya ve Moleküler Biyoloji Doktora",
        "Biyokimya ve Moleküler Biyoloji Tezli Yüksek Lisans",
        "Cerrahi Hastalıkları Hemşireliği Tezli Yüksek Lisans",
        "Fizyoloji Doktora",
        "Fizyoloji Tezli Yüksek Lisans",
        "Fizyoterapi ve Rehabilitasyon Tezli Yüksek Lisans Programı",
        "Genom Çalışmaları Tezli Yüksek Lisans Programı (İngilizce)",
        "Hemşirelik Doktora",
        "Hemşirelik Tezsiz Yüksek Lisans",
        "Histoloji ve Embriyoloji Tezli Yüksek Lisans",
        "Medikal Biyoteknoloji Doktora (İngilizce)",
        "Medikal Biyoteknoloji Tezli Yüksek Lisans (İngilizce)",
        "Medikal Biyoteknoloji Tezsiz Yüksek Lisans (İngilizce)",
        "Perfüzyon Teknikleri Tezli Yüksek Lisans",
        "Sağlık Fiziği Tezli Yüksek Lisans",
        "Sağlık Yönetimi Doktora",
        "Sağlık Yönetimi Tezli Yüksek Lisans",
        "Sağlık Yönetimi Tezsiz Yüksek Lisans",
        "Sinir Bilimi Doktora",
        "Spor Fizyoterapisi Tezli Yüksek Lisans",
        "Sporcu Beslenmesi Tezli Yüksek Lisans",
        "Sporcu Beslenmesi Tezsiz Yüksek Lisans",
        "Translasyonel Tıp Doktora (İngilizce)",
        "Tıbbi Mikrobiyoloji Doktora Programı",
        "Tıbbi Mikrobiyoloji Tezli Yüksek Lisans Programı",
        "Tıp Eğitimi Doktora (İngilizce)",
        "Tıp Eğitimi Tezli Yüksek Lisans (İngilizce)",
        "Yoğun Bakım Hemşireliği Tezli Yüksek Lisans",
        "Çocuk Sağlığı ve Hastalıkları Hemşireliği Tezli Yüksek Lisans",
        "İlaç Endüstrisinde Yönetim Tezsiz Yüksek Lisans",
        "İç Hastalıkları Hemşireliği Tezli Yüksek Lisans",
    ],
    "Sosyal Bilimler Enstitüsü": [
        "Bilişsel Nöropsikoloji Tezli Yüksek Lisans",
        "Klinik Psikoloji Tezli Yüksek Lisans",
        "Sağlık Sosyolojisi Tezli Yüksek Lisans",
        "Sağlık Sosyolojisi Tezsiz Yüksek Lisans",
    ],
    "Fen Bilimleri Enstitüsü": [
        "Biyomalzeme Doktora Programı (İngilizce)",
        "Biyomalzeme Tezli Yüksek Lisans Programı (İngilizce)",
        "Biyomedikal Mühendisliği Doktora (İngilizce)",
        "Biyomedikal Mühendisliği Tezli Yüksek Lisans (İngilizce)",
        "Moleküler Biyoloji ve Genetik Doktora (İngilizce)",
        "Moleküler Biyoloji ve Genetik Tezli Yüksek Lisans (İngilizce)",
        "Moleküler Ve Translasyonel Biyotıp Tezli Yüksek Lisans (İngilizce)",
    ],
    "Senoloji Araştırma Enstitüsü": [
        "Genel Senoloji Tezli Yüksek Lisans",
        "Meme Görüntüleme Teknikleri ve Teknolojileri Tezli Yüksek Lisans",
    ],
}


def clean_program_label(name: str) -> str:
    cleaned = (name or "").strip()
    cleaned = cleaned.replace(" - Program Bilgileri", "")
    cleaned = cleaned.replace("Program Hakkında", "")
    cleaned = cleaned.replace("(English)", "(İngilizce)")
    cleaned = " ".join(cleaned.split())
    return cleaned


def build_program_structure():
    structure = []
    for category_name, faculty_names in PROGRAM_CATEGORY_ORDER.items():
        faculties = []
        for faculty_name in faculty_names:
            existing_department_names = set(
                clean_program_label(name)
                for name in Department.objects.filter(faculty__name=faculty_name)
                .values_list("name", flat=True)
            )
            departments = [
                name
                for name in CANONICAL_PROGRAMS.get(faculty_name, [])
                if name in existing_department_names or faculty_name in {"Tıp Fakültesi", "Eczacılık Fakültesi"}
            ]
            faculties.append({"name": faculty_name, "depts": departments})
        structure.append({"cat": category_name, "facs": faculties})
    return structure


def login_view(request):
    if request.session.get('user_id'):
        return redirect('chat')
    return render(request, 'chat/login.html')


@csrf_exempt
def login_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Sadece POST isteği kabul edilir.'}, status=405)
    try:
        data = json.loads(request.body)
        user_type = data.get('user_type')

        if user_type == 'student':
            student_number = data.get('student_number', '').strip()
            password = data.get('password', '').strip()
            if not student_number:
                return JsonResponse({'error': 'Öğrenci numarası gereklidir.'}, status=400)
            user, created = UserProfile.objects.get_or_create(
                student_number=student_number,
                defaults={
                    'name': f'Öğrenci {student_number}',
                    'user_type': 'student'
                }
            )
            request.session['user_id'] = user.id
            request.session['user_name'] = user.name
            request.session['user_type'] = 'student'
            return JsonResponse({
                'success': True,
                'user_name': user.name,
                'user_type': 'student',
                'redirect': '/'
            })

        elif user_type == 'guest':
            name = data.get('name', '').strip()
            email = data.get('email', '').strip()
            if not name:
                return JsonResponse({'error': 'Ad soyad gereklidir.'}, status=400)
            user = UserProfile.objects.create(
                name=name,
                email=email if email else None,
                user_type='guest'
            )
            request.session['user_id'] = user.id
            request.session['user_name'] = user.name
            request.session['user_type'] = 'guest'
            return JsonResponse({
                'success': True,
                'user_name': user.name,
                'user_type': 'guest',
                'redirect': '/'
            })

        return JsonResponse({'error': 'Geçersiz kullanıcı tipi.'}, status=400)

    except Exception as e:
        return JsonResponse({'error': 'Bir hata oluştu.'}, status=500)


def logout_view(request):
    request.session.flush()
    return redirect('login')


def chat_view(request):
    if not request.session.get('user_id'):
        return redirect('login')

    user_id = request.session.get('user_id')
    requested_session_id = request.GET.get('session')
    session_id = requested_session_id or request.session.get('chat_session_id')
    user_name = request.session.get('user_name', 'Kullanıcı')
    user_type = request.session.get('user_type', 'guest')

    if not session_id:
        session = ChatSession.objects.create(user_profile_id=user_id)
        request.session['chat_session_id'] = str(session.session_id)
        session_id = str(session.session_id)

    try:
        session = ChatSession.objects.get(session_id=session_id, user_profile_id=user_id)
        messages = session.messages.all()
    except ChatSession.DoesNotExist:
        session = ChatSession.objects.create(user_profile_id=user_id)
        request.session['chat_session_id'] = str(session.session_id)
        session_id = str(session.session_id)
        messages = []

    sessions = (
        ChatSession.objects.filter(user_profile_id=user_id)
        .prefetch_related(Prefetch("messages", queryset=ChatMessage.objects.order_by("created_at")))
        .order_by("-created_at")
    )
    session_summaries = []
    for item in sessions:
        first_message = item.messages.all()[0] if item.messages.exists() else None
        session_summaries.append(
            {
                "session_id": str(item.session_id),
                "preview": first_message.question if first_message else "Yeni sohbet",
                "message_count": item.messages.count(),
                "is_active": str(item.session_id) == str(session.session_id),
            }
        )

    return render(request, 'chat/index.html', {
        'messages': messages,
        'session_id': str(session.session_id),
        'sessions': session_summaries,
        'program_structure_json': json.dumps(
            build_program_structure(), ensure_ascii=False
        ),
        'user_name': user_name,
        'user_type': user_type,
    })


@csrf_exempt
def chat_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Sadece POST isteği kabul edilir.'}, status=405)
    try:
        data = json.loads(request.body)
        question = data.get('question', '').strip()
        session_id = data.get('session_id', '')
        if not question:
            return JsonResponse({'error': 'Lütfen bir soru yazın.'}, status=400)
        try:
            session = ChatSession.objects.get(
                session_id=session_id,
                user_profile_id=request.session.get('user_id'),
            )
        except ChatSession.DoesNotExist:
            session = ChatSession.objects.create(user_profile_id=request.session.get('user_id'))
            request.session['chat_session_id'] = str(session.session_id)

        effective_question = question
        last_message = session.messages.order_by('-created_at').first()
        if last_message and should_expand_with_context(question):
            effective_question = f"{last_message.question} {question}"

        result = answer_question(question=effective_question, language='tr')
        answer = result['answer']

        ChatMessage.objects.create(
            session=session,
            question=question,
            answer=answer
        )

        return JsonResponse(
            {
                'answer': answer,
                'session_id': str(session.session_id),
                'sources': result['sources'],
            }
        )

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Gecersiz JSON formati.'}, status=400)
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'error': f'Hata: {e}'}, status=500)


@csrf_exempt
def search_api(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Sadece GET isteği kabul edilir.'}, status=405)
    query = request.GET.get('q', '').strip()
    if not query:
        return JsonResponse({'results': []})
    results = retrieve_context(query, language='tr', limit=8)
    data = [
        {
            'title': r.title,
            'snippet': r.body[:200],
            'url': r.url,
            'category': r.category,
            'source_type': r.source_type,
        }
        for r in results
    ]
    return JsonResponse({'results': data, 'query': query})


@csrf_exempt
def feedback_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Sadece POST isteği kabul edilir.'}, status=405)
    try:
        data = json.loads(request.body)
        return JsonResponse({'status': 'ok', 'helpful': data.get('helpful')})
    except Exception:
        return JsonResponse({'error': 'Hata olustu.'}, status=500)


@csrf_exempt
def new_session_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Sadece POST isteği kabul edilir.'}, status=405)
    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({'error': 'Oturum bulunamadı.'}, status=401)

    session = ChatSession.objects.create(user_profile_id=user_id)
    request.session['chat_session_id'] = str(session.session_id)
    return JsonResponse(
        {
            'success': True,
            'session_id': str(session.session_id),
            'redirect': f'/?session={session.session_id}',
        }
    )


@csrf_exempt
def delete_session_api(request, session_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Sadece POST isteği kabul edilir.'}, status=405)
    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({'error': 'Oturum bulunamadı.'}, status=401)

    try:
        session = ChatSession.objects.get(session_id=session_id, user_profile_id=user_id)
    except ChatSession.DoesNotExist:
        return JsonResponse({'error': 'Sohbet bulunamadı.'}, status=404)

    was_current = str(request.session.get('chat_session_id')) == str(session.session_id)
    session.delete()

    replacement = ChatSession.objects.filter(user_profile_id=user_id).order_by('-created_at').first()
    if was_current:
        if replacement:
            request.session['chat_session_id'] = str(replacement.session_id)
            redirect_url = f'/?session={replacement.session_id}'
        else:
            new_session = ChatSession.objects.create(user_profile_id=user_id)
            request.session['chat_session_id'] = str(new_session.session_id)
            redirect_url = f'/?session={new_session.session_id}'
    else:
        current_session_id = request.session.get('chat_session_id')
        redirect_url = f'/?session={current_session_id}' if current_session_id else '/'

    return JsonResponse({'success': True, 'redirect': redirect_url})


@csrf_exempt
def clear_sessions_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Sadece POST isteği kabul edilir.'}, status=405)
    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({'error': 'Oturum bulunamadı.'}, status=401)

    ChatSession.objects.filter(user_profile_id=user_id).delete()
    session = ChatSession.objects.create(user_profile_id=user_id)
    request.session['chat_session_id'] = str(session.session_id)
    return JsonResponse(
        {'success': True, 'redirect': f'/?session={session.session_id}'}
    )
