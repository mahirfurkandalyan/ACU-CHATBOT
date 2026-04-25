from django.core.management.base import BaseCommand

from chat.models import UserProfile


MOCK_STUDENTS = [
    {"name": "Ayse Yilmaz", "student_number": "221401001"},
    {"name": "Mehmet Demir", "student_number": "221401002"},
    {"name": "Zeynep Kaya", "student_number": "221401003"},
    {"name": "Can Arslan", "student_number": "221401004"},
]

MOCK_GUESTS = [
    {"name": "Demo Guest", "email": "guest@example.com"},
    {"name": "Aday Ogrenci", "email": "aday@example.com"},
]


class Command(BaseCommand):
    help = "Create mock student and guest users for demo logins."

    def handle(self, *args, **options):
        created_students = 0
        created_guests = 0

        for item in MOCK_STUDENTS:
            _, created = UserProfile.objects.get_or_create(
                student_number=item["student_number"],
                defaults={
                    "name": item["name"],
                    "user_type": "student",
                },
            )
            if created:
                created_students += 1

        for item in MOCK_GUESTS:
            _, created = UserProfile.objects.get_or_create(
                email=item["email"],
                defaults={
                    "name": item["name"],
                    "user_type": "guest",
                },
            )
            if created:
                created_guests += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Mock users ready. Students created: {created_students}, guests created: {created_guests}"
            )
        )
        self.stdout.write("Student login demo numbers:")
        for item in MOCK_STUDENTS:
            self.stdout.write(f"- {item['student_number']} ({item['name']})")
        self.stdout.write("Note: current login flow does not validate password; any non-empty password works.")
