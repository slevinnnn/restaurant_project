"""agregar mesa_asignada_at

Revision ID: agregar_mesa_asignada_at
Revises: corregir_password_hash
Create Date: 2025-08-21 04:45:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'agregar_mesa_asignada_at'
down_revision = 'corregir_password_hash'
branch_labels = None
depends_on = None

def upgrade():
    # Agregar la columna mesa_asignada_at
    with op.batch_alter_table('cliente', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mesa_asignada_at', sa.DateTime(), nullable=True))

def downgrade():
    # Remover la columna mesa_asignada_at
    with op.batch_alter_table('cliente', schema=None) as batch_op:
        batch_op.drop_column('mesa_asignada_at')
