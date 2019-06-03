import logging
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from . import settings
from .minio_storage import storage
from .files import file_info

logger = logging.getLogger('apiqa-storage')  # noqa


__all__ = [
    'CreateAttachFilesSerializers',
    'AttachFilesSerializers',
]


class AttachmentField(serializers.FileField):
    def to_representation(self, data):
        return {
            key: value for key, value in data.items()
            if key in ('uid', 'name', 'size', 'content_type', 'created')
        }


class AttachFilesSerializers(serializers.Serializer):  # noqa: pylint=abstract-method
    attachments = serializers.ListField(
        child=AttachmentField(),
        max_length=settings.MINIO_STORAGE_MAX_FILES_COUNT,
        default=list,
    )

    def validate_attachments(self, value):  # noqa
        """
        Длина имени файла тут не валидируется. Смотри files.py # slugify_name
        """
        # Validate files size
        for attach_file in value:
            if attach_file.size > settings.MAX_FILE_SIZE:
                raise ValidationError(
                    f'Max size of attach file: '
                    f'{settings.MINIO_STORAGE_MAX_FILE_SIZE}'
                )

        return value


def upload_files(validated_data: dict):
    attachments = validated_data.pop('attachments', [])

    attach_files_info = [
        file_info(attach_file) for attach_file in attachments
    ]

    # Upload files
    for attach_file in attach_files_info:
        # TODO: В середине процесса может случиться ошибка
        # из хранилки не удалятся загруженные данные
        storage.file_put(attach_file)

    validated_data['attachments'] = [
        {
            'uid': attach_file.uid,
            'bucket_name': storage.bucket_name,
            'name': attach_file.name,
            'created': attach_file.created,
            'path': attach_file.path,
            'size': attach_file.size,
            'content_type': attach_file.content_type,
        }
        for attach_file in attach_files_info
    ]
    return attach_files_info


def delete_files(attach_files_info: list):
    for attach_file in attach_files_info:
        # noinspection PyBroadException
        try:
            storage.file_delete(attach_file.path)
        except Exception:  # noqa
            logger.exception("Delete file failed: %s from bucket: %s",
                             attach_file.path, storage.bucket_name)


class CreateAttachFilesSerializers(AttachFilesSerializers, serializers.ModelSerializer):  # noqa: pylint=abstract-method
    def create(self, validated_data):
        attach_files_info = upload_files(validated_data)

        try:
            return super().create(validated_data)
        except Exception:
            # Delete files if save model failed
            delete_files(attach_files_info)
            raise
