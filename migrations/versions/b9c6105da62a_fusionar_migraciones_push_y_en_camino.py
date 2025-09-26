"""Fusionar migraciones push y en_camino

Revision ID: b9c6105da62a
Revises: 208974d72e4f, b7c9d2e1f3a4
Create Date: 2025-09-26 16:01:38.546683

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b9c6105da62a'
down_revision = ('208974d72e4f', 'b7c9d2e1f3a4')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
