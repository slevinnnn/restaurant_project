-- SQL para crear la tabla push_subscription en PostgreSQL
-- Ejecutar este comando en tu base de datos PostgreSQL

CREATE TABLE push_subscription (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL,
    endpoint TEXT NOT NULL,
    p256dh_key VARCHAR(255) NOT NULL,
    auth_key VARCHAR(255) NOT NULL,
    user_agent TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'America/Santiago'),
    is_active BOOLEAN DEFAULT true,
    
    -- Llave foránea
    CONSTRAINT fk_push_subscription_cliente_id 
        FOREIGN KEY (cliente_id) REFERENCES cliente(id)
);

-- Índices para optimizar consultas
CREATE INDEX idx_cliente_active ON push_subscription (cliente_id, is_active);
CREATE INDEX idx_endpoint ON push_subscription (endpoint);

-- Verificar que la tabla se creó correctamente
SELECT * FROM push_subscription LIMIT 1;