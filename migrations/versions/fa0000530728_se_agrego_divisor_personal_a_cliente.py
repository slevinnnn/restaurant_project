"""se agrego divisor personal a cliente (placeholder)

Revision ID: fa0000530728
Revises: 5b041321ac29
Create Date: 2025-09-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fa0000530728'
down_revision = '5b041321ac29'
branch_labels = None
depends_on = None


def upgrade():
    # This placeholder migration exists to satisfy an existing database revision.
    # No schema changes are applied here.
    pass


def downgrade():
    # No-op downgrade matching the no-op upgrade.
    pass
