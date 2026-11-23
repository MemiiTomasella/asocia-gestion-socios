"""Crea los roles del sistema como grupos de Django (Secretaría, Tesorería, Comisión directiva y Socio)."""
from django.db import migrations

ROLES = ["Secretaría", "Tesorería", "Comisión directiva", "Socio"]


def crear_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for nombre in ROLES:
        Group.objects.get_or_create(name=nombre)


def borrar_roles(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=ROLES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("socios", "0004_portal_socio_y_avisos_de_pago"),
    ]
    operations = [migrations.RunPython(crear_roles, borrar_roles)]
