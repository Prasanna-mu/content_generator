# Spring Boot: A Brief Overview

## What is Spring Boot?

Spring Boot is an open-source Java framework built on top of the Spring Framework. It removes most of the manual configuration Spring normally needs, so you can create production-ready applications quickly, often with just a `main` method and a few annotations.

## Why use it?

- **Auto-configuration**: Detects the libraries on your classpath and configures them automatically (e.g. add a database driver and it sets up a `DataSource`).
- **Starter dependencies**: Curated bundles like `spring-boot-starter-web` or `spring-boot-starter-data-jpa` replace long lists of individual dependencies.
- **Embedded server**: Tomcat (or Jetty/Undertow) is bundled, so you run the app as a plain JAR with `java -jar`. No separate server install.
- **Production features**: Built-in health checks, metrics, and monitoring via Spring Boot Actuator.
- **Minimal boilerplate**: Little to no XML; configuration lives in `application.properties` or `application.yml`.

## Core building blocks

| Concept | Purpose |
|---|---|
| `@SpringBootApplication` | Entry-point annotation combining configuration, auto-configuration, and component scanning |
| `@RestController` | Marks a class that handles HTTP requests and returns JSON |
| `@Service` | Holds business logic |
| `@Repository` | Handles data access (often with Spring Data JPA) |
| `@Autowired` / constructor injection | Dependency injection: Spring supplies the objects a class needs |

## Minimal example

```java
@SpringBootApplication
public class DemoApplication {
    public static void main(String[] args) {
        SpringApplication.run(DemoApplication.class, args);
    }
}

@RestController
class HelloController {
    @GetMapping("/hello")
    public String hello() {
        return "Hello, Spring Boot!";
    }
}
```

Run it, then visit `http://localhost:8080/hello`.

## Typical project structure

```
src/main/java/com/example/demo/
├── DemoApplication.java     # entry point
├── controller/              # REST endpoints
├── service/                 # business logic
├── repository/              # database access
└── model/                   # entities / DTOs
src/main/resources/
└── application.properties   # configuration
```

## Common use cases

- REST APIs and microservices
- Web applications
- Backend services with database access (SQL/NoSQL)
- Event-driven and messaging systems (Kafka, RabbitMQ)

## Getting started

1. Generate a project at [start.spring.io](https://start.spring.io) (choose Maven/Gradle, Java version, and dependencies).
2. Open it in your IDE (IntelliJ IDEA, Eclipse, VS Code).
3. Run the main class, or use `./mvnw spring-boot:run`.

## Summary

Spring Boot = Spring's power with far less setup. It gives you sensible defaults, an embedded server, and production tooling, letting you focus on business logic instead of configuration.
