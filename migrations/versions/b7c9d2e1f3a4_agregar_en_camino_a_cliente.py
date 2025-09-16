"""agregar en_camino a cliente

Revision ID: b7c9d2e1f3a4
Revises: a23f9c7b8d10
Create Date: 2025-09-16 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c9d2e1f3a4'
down_revision = 'a23f9c7b8d10'
branch_labels = None
depends_on = None


def upgrade():
    # Add en_camino as a nullable Boolean to cliente
    with op.batch_alter_table('cliente', schema=None) as batch_op:
        batch_op.add_column(sa.Column('en_camino', sa.Boolean(), nullable=True))


def downgrade():
    # Drop en_camino column
    with op.batch_alter_table('cliente', schema=None) as batch_op:
        batch_op.drop_column('en_camino')
