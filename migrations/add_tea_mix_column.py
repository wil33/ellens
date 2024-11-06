"""Add is_tea_mix column to inventory_item

Revision ID: xxx
Revises: xxx
Create Date: 2024-03-xx
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('inventory_item', sa.Column('is_tea_mix', sa.Boolean(), nullable=False, server_default='0'))

def downgrade():
    op.drop_column('inventory_item', 'is_tea_mix') 