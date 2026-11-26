import factory
from factory.django import DjangoModelFactory

from accounts import services
from accounts.models import ConsentRecord, User


class UserFactory(DjangoModelFactory):
    """A signed-up player who has finished the first-time profile (name and consent)."""

    class Meta:
        model = User
        skip_postgeneration_save = True

    phone = factory.Sequence(lambda n: f"+9477{n:07d}")
    name = factory.Sequence(lambda n: f"Player {n}")

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        return model_class.objects.create_user(*args, **kwargs)

    @factory.post_generation
    def consented(obj, create, extracted, **kwargs):
        if create and extracted is not False:
            for document, version in services.CURRENT_DOCUMENTS.items():
                ConsentRecord.objects.create(user=obj, document=document, version=version)
