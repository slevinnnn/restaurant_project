"""No-op migration to replace stray empty file

Revision ID: b1c2d3e4f5a6
Revises: 4f9b2e7a3466
Create Date: 2025-08-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b1c2d3e4f5a6'
down_revision = '4f9b2e7a3466'
branch_labels = None
depends_on = None


def upgrade():
	# This migration intentionally does nothing.
	pass


def downgrade():
	# This migration intentionally does nothing.
	pass

