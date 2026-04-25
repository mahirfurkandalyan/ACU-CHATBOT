from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0004_merge_0002_userprofile_chatsession_user_profile_0003_extend_schema"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="chatmessage",
            options={
                "ordering": ["created_at"],
                "verbose_name": "Chat Mesajı",
                "verbose_name_plural": "Chat Mesajları",
            },
        ),
        migrations.AlterModelOptions(
            name="chatsession",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Chat Oturumu",
                "verbose_name_plural": "Chat Oturumları",
            },
        ),
        migrations.AlterModelOptions(
            name="universitycontent",
            options={
                "ordering": ["-scraped_at"],
                "verbose_name": "Üniversite İçeriği",
                "verbose_name_plural": "Üniversite İçerikleri",
            },
        ),
        migrations.AlterModelOptions(
            name="userprofile",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Kullanıcı Profili",
                "verbose_name_plural": "Kullanıcı Profilleri",
            },
        ),
        migrations.RenameIndex(
            model_name="universitycontent",
            new_name="chat_univer_categor_56fa64_idx",
            old_name="chat_unicontent_category_idx",
        ),
        migrations.RenameIndex(
            model_name="universitycontent",
            new_name="chat_univer_languag_fb3b41_idx",
            old_name="chat_unicontent_language_idx",
        ),
        migrations.RenameIndex(
            model_name="universitycontent",
            new_name="chat_univer_is_acti_90c563_idx",
            old_name="chat_unicontent_active_idx",
        ),
    ]
