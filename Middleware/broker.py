import json
from uuid import uuid4
from datetime import datetime, timezone

import aio_pika
from aio_pika import Message, DeliveryMode


_connection = None
_publish_channel = None
_consume_channel = None


async def conectar_broker(url: str):
    global _connection, _publish_channel, _consume_channel

    _connection = await aio_pika.connect_robust(url)

    # Canal exclusivo do produtor
    _publish_channel = await _connection.channel()

    # Canal exclusivo do consumidor
    _consume_channel = await _connection.channel()

    await _consume_channel.set_qos(prefetch_count=10)

    print("Conectado ao RabbitMQ!")


async def desconectar_broker():
    global _connection, _publish_channel, _consume_channel

    if _connection and not _connection.is_closed:
        await _connection.close()

    _connection = None
    _publish_channel = None
    _consume_channel = None

    print("Conexão com RabbitMQ encerrada.")


async def publicar_mensagem(
    fila: str,
    dados: dict,
    correlation_id: str = None
):
    """PRODUTOR: publica mensagens no RabbitMQ."""

    if _publish_channel is None or _publish_channel.is_closed:
        raise RuntimeError("Canal do produtor não está conectado.")

    await _publish_channel.declare_queue(
        fila,
        durable=True
    )

    mensagem = Message(
        body=json.dumps(
            dados,
            ensure_ascii=False
        ).encode("utf-8"),
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="application/json",
        message_id=str(uuid4()),
        correlation_id=correlation_id,
        timestamp=datetime.now(timezone.utc)
    )

    await _publish_channel.default_exchange.publish(
        mensagem,
        routing_key=fila
    )

    print(f"[PRODUTOR] Mensagem publicada: {fila}")


async def consumir_mensagens(fila: str, callback):
    """CONSUMIDOR: recebe mensagens e executa o callback."""

    if _consume_channel is None or _consume_channel.is_closed:
        raise RuntimeError("Canal do consumidor não está conectado.")

    queue = await _consume_channel.declare_queue(
        fila,
        durable=True
    )

    print(f"[CONSUMIDOR] Aguardando mensagens: {fila}")

    async with queue.iterator() as iterator:
        async for mensagem in iterator:

            async with mensagem.process(requeue=False):
                dados = json.loads(
                    mensagem.body.decode("utf-8")
                )

                await callback(dados)
