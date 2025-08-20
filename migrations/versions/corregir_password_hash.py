"""Aumentar tamaño password_hash

Revision ID: corregir_password_hash
Revises: 8ee63bfb2053
Create Date: 2025-08-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'corregir_password_hash'
down_revision = '8ee63bfb2053'
branch_labels = None
depends_on = None

def upgrade():
    # Aumentar el tamaño del campo password_hash de 128 a 255 caracteres
    with op.batch_alter_table('trabajador', schema=None) as batch_op:
        batch_op.alter_column('password_hash',
                              existing_type=sa.VARCHAR(length=128),
                              type_=sa.String(length=255),
                              existing_nullable=False)

def downgrade():
    # Revertir el cambio (reducir de 255 a 128 caracteres)
    with op.batch_alter_table('trabajador', schema=None) as batch_op:
        batch_op.alter_column('password_hash',
                              existing_type=sa.VARCHAR(length=255),
                              type_=sa.String(length=128),
                              existing_nullable=False)
