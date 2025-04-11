import logging
import functools
import inspect
import time
from pathlib import Path

# Настройка логгера для записи в файл
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # Устанавливаем уровень INFO для логгера декоратора

# Создаем директорию для логов, если она не существует
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# Создаем файловый обработчик
log_file = log_dir / "method_calls.log"
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.INFO)

# Настраиваем формат логов
formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(formatter)

# Добавляем обработчик к логгеру
logger.addHandler(file_handler)

def log_method_call(func):
    """
    Декоратор для логирования вызовов методов.
    Логирует:
    - Начало выполнения метода
    - Параметры метода
    - Время выполнения
    - Завершение выполнения
    Записывает логи в файл method_calls.log в папке logs.
    """
    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        # Получаем имя класса и метода
        class_name = args[0].__class__.__name__ if args else 'Unknown'
        method_name = func.__name__
        
        # Формируем строку с параметрами
        params = []
        if len(args) > 1:  # Пропускаем self
            params.extend([f"arg{i}={arg}" for i, arg in enumerate(args[1:])])
        params.extend([f"{k}={v}" for k, v in kwargs.items()])
        params_str = ", ".join(params)
        
        # Логируем начало выполнения
        logger.info(f"▶️ {class_name}.{method_name} начал выполнение | Параметры: {params_str}")
        
        # Замеряем время выполнения
        start_time = time.time()
        
        try:
            # Выполняем метод
            result = await func(*args, **kwargs)
            
            # Логируем успешное завершение
            execution_time = time.time() - start_time
            logger.info(f"✅ {class_name}.{method_name} завершил выполнение за {execution_time:.2f}с")
            
            return result
            
        except Exception as e:
            # Логируем ошибку
            execution_time = time.time() - start_time
            logger.error(f"❌ {class_name}.{method_name} завершился с ошибкой за {execution_time:.2f}с: {str(e)}")
            raise
    
    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        # Получаем имя класса и метода
        class_name = args[0].__class__.__name__ if args else 'Unknown'
        method_name = func.__name__
        
        # Формируем строку с параметрами
        params = []
        if len(args) > 1:  # Пропускаем self
            params.extend([f"arg{i}={arg}" for i, arg in enumerate(args[1:])])
        params.extend([f"{k}={v}" for k, v in kwargs.items()])
        params_str = ", ".join(params)
        
        # Логируем начало выполнения
        logger.info(f"▶️ {class_name}.{method_name} начал выполнение | Параметры: {params_str}")
        
        # Замеряем время выполнения
        start_time = time.time()
        
        try:
            # Выполняем метод
            result = func(*args, **kwargs)
            
            # Логируем успешное завершение
            execution_time = time.time() - start_time
            logger.info(f"✅ {class_name}.{method_name} завершил выполнение за {execution_time:.2f}с")
            
            return result
            
        except Exception as e:
            # Логируем ошибку
            execution_time = time.time() - start_time
            logger.error(f"❌ {class_name}.{method_name} завершился с ошибкой за {execution_time:.2f}с: {str(e)}")
            raise
    
    # Возвращаем соответствующий wrapper в зависимости от того, является ли функция асинхронной
    return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper